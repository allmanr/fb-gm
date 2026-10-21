#!/usr/bin/env python3
"""Rebuild the weekly-value draft board from the frozen, editable input CSV.

Preview: python3 rebuild_board.py
Write:   python3 rebuild_board.py --write
Check:   python3 rebuild_board.py --test
Audit:   python3 rebuild_board.py --audit
Blend:   python3 rebuild_board.py --blend [--write]   (refetch 2026 Sleeper game logs)
Replay:  python3 rebuild_board.py --blend --season 2025 --through-week 4   (preview only)

V is expected weekly lock-in surplus: each starter keeps one game a week,
chosen by optimal stopping over that week's games, compared against a
healthy replacement facing the same weekly schedule count. Availability and
expert weights are judgment calls; see prep-notes.md. In season, --blend
shrinks actual FP/g toward the frozen projection (BLEND_K) and saves the
actuals snapshot in board-actuals.csv; plain --write reuses that snapshot.
"""
import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import urllib.request
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

HERE = Path(__file__).resolve().parent
# Team-weeks by games played, 2025-26 regular season (Sleeper weekly stats; see fit_lockin.py).
WEEK_GAMES = {1: 16, 2: 97, 3: 302, 4: 331, 5: 6}
# Per-game FP coefficient of variation vs season mean, same data (151 players,
# 40+ games, 25+ FP/g). Player-specific residual CV was not stable (split-half
# reliability 0.07-0.30), so CV depends on the mean only: no ceiling premium.
CV_A, CV_B = 1.292, -0.247
# League scoring (CLAUDE.md), applied to Sleeper per-game stat rows.
SCORING = {'pts': 1.0, 'reb': 1.5, 'ast': 2.0, 'stl': 2.5, 'blk': 2.5, 'to': -2.0,
           'fgm': 2.0, 'fga': -1.0, 'ftm': 1.0, 'ftmi': -1.0, 'tpm': 1.0}
SEASON = 2026
# In-season update: post = prior + n/(n+k)*(actual - prior) after n games played.
# Fit by fit_lockin.py --fit-blend on Sleeper 2025-26 logs, prior = the player's
# 2024-25 FP/g (>= 10 GP, >= 20 FP/g), target = rest-of-season FP/g, n = 3/5/10/20:
# k = 6.5, pooled RMSE 5.82 vs 7.43 prior-only and 7.74 actual-only; per-n best k
# 6.0-7.5. 2024-25 out-of-sample (prior 2023-24): 5.22 at k = 6.5 vs 5.19 at its own
# best k = 9.0. Blending minutes/g and FP/minute separately gained < 1%, so one k.
# A real projection should beat last season's FP/g as a prior, so this k probably
# leans slightly toward actuals.
BLEND_K = 6.5
# No prior season (< 10 GP): constant league-mean prior, same fit: RMSE 6.54, 2024-25
# check 6.44. Survivor-fitted (>= 10 games left), so optimistic for deep rookies.
NO_PRIOR_K, NO_PRIOR_PPG = 2.5, 28.4
ADD_MIN_GAMES = 3
ADD_GP = 74  # median projected GP on the frozen board; adds have no availability input
ACTUALS = HERE / 'board-actuals.csv'
ACTUAL_FIELDS = ['name', 'games', 'actual_ppg', 'through', 'prior_ppg', 'prior_k',
                 'positions', 'injury_status', 'note']
Z_GRID = [NormalDist().inv_cdf((i + 0.5) / 200) for i in range(200)]


def lock_values(ppg, games=5):
    """Expected locked score with 0..games games left, optimal stopping."""
    cv = min(0.6, max(0.2, CV_A + CV_B * math.log(max(ppg, 1))))
    draws = [max(0.0, ppg * (1 + cv * z)) for z in Z_GRID]
    values = [0.0, sum(draws) / len(draws)]
    for _ in range(games - 1):
        values.append(sum(max(d, values[-1]) for d in draws) / len(draws))
    return values


def week_value(ppg, gp, cluster, replacement_ppg):
    """Expected weekly surplus over a matched-schedule healthy replacement, plus usable-week share.

    A cluster share of missed games removes whole weeks; the rest are missed
    one game at a time (binomial) and averaged before comparing against a
    healthy replacement facing the same schedule count n.
    """
    whole_week = cluster * (1 - gp / 82)
    game_miss = (1 - cluster) * (1 - gp / 82) / (1 - whole_week)
    values = lock_values(ppg)
    rep_values = lock_values(replacement_ppg)
    total = sum(WEEK_GAMES.values())
    surplus = usable = 0.0
    for n, weeks in WEEK_GAMES.items():
        w = weeks / total
        expected_n = sum(
            math.comb(n, k) * (1 - game_miss) ** k * game_miss ** (n - k) * values[k]
            for k in range(n + 1)
        )
        surplus += w * max(0.0, expected_n - rep_values[n])
        usable += w * (1 - game_miss ** n)
    return (1 - whole_week) * surplus, (1 - whole_week) * usable


def healthy_lock(ppg):
    values = lock_values(ppg)
    return sum(values[n] * w for n, w in WEEK_GAMES.items()) / sum(WEEK_GAMES.values())


def expert_weight(deviation):
    return 0.25 / (1 + (deviation / 15) ** 2)


def percentile_score(curve, rank):
    index = max(0, rank - 1)
    low = min(int(index), len(curve) - 1)
    high = min(low + 1, len(curve) - 1)
    return curve[low] + (curve[high] - curve[low]) * (index - int(index))


def fetch_week(season, week):
    """Compact Sleeper NBA stat rows for one fantasy week, cached in .cache/.

    Reuse earlier-season caches. Refresh current-season weeks: a later week
    having games does not prove that an earlier cached snapshot is complete.
    """
    cache = HERE / '.cache' / f'stats-{season}-{week:02d}.json'
    if cache.exists() and season < SEASON:
        return json.loads(cache.read_text())
    url = f'https://api.sleeper.com/stats/nba/{season}/{week}?season_type=regular'
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        rows = [{'player_id': str(r.get('player_id') or ''), 'game_id': r.get('game_id'),
                 'team': r.get('team'), 'opponent': r.get('opponent'), 'date': r.get('date'),
                 'stats': {k: v for k, v in (r.get('stats') or {}).items()
                           if k in SCORING or k == 'sp'}}
                for r in json.load(response)]
    cache.parent.mkdir(exist_ok=True)
    cache.with_suffix('.tmp').write_text(json.dumps(rows))
    os.replace(cache.with_suffix('.tmp'), cache)
    return rows


def season_weeks(season, through_week=25):
    """{week: rows} for weeks 1..through_week, stopping at the first week with no rows."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        fetched = list(pool.map(lambda w: fetch_week(season, w), range(1, through_week + 1)))
    weeks = {}
    for week, rows in enumerate(fetched, 1):
        if not rows:
            break
        weeks[week] = rows
    return weeks


def game_logs(weeks):
    """player_id -> [(date, game_id, FP, minutes)] for games with seconds played > 0, in date order."""
    logs = defaultdict(list)
    for rows in weeks.values():
        for row in rows:
            stats = row['stats']
            if row['player_id'].isdigit() and (stats.get('sp') or 0) > 0:
                fp = sum(stats.get(k, 0.0) * w for k, w in SCORING.items())
                logs[row['player_id']].append((row['date'] or '', row['game_id'] or '', fp, stats['sp'] / 60))
    return {pid: sorted(games) for pid, games in logs.items()}


def load_inputs():
    with (HERE / 'board-inputs.csv').open(newline='') as source:
        rows = list(csv.DictReader(source))
    numeric = ('original_rank', 'gp', 'ppg', 'espn_delta', 'ecr', 'ecr_sd',
               'cluster', 'sleeper_rank')
    names = set()
    for row in rows:
        row['draft_exclude'] = (row.get('draft_exclude') or '').strip()
        row['ecr_review'] = (row.get('ecr_review') or '').strip()
        if row['name'] in names:
            raise ValueError('Duplicate player: ' + row['name'])
        names.add(row['name'])
        for key in numeric:
            row[key] = float(row[key]) if row[key] else None
        if row['ppg'] is not None:
            if not 0 < row['gp'] <= 82 or not 0 <= row['cluster'] <= 1:
                raise ValueError('Invalid availability: ' + row['name'])
            if row['ppg'] < 0 or not math.isfinite(row['ppg']):
                raise ValueError('Invalid projection: ' + row['name'])
        if row['ecr'] is not None and (row['ecr'] < 1 or row['ecr_sd'] < 0):
            raise ValueError('Invalid expert ranking: ' + row['name'])
    return rows


def blend(prior, row):
    """Shrink actual FP/g toward the prior after row['games'] games; exactly prior at 0 games."""
    n = row.get('games') or 0
    if not n:
        return prior
    return prior + n / (n + row.get('prior_k', BLEND_K)) * (row['actual_ppg'] - prior)


def load_actuals():
    """In-season snapshot written by --blend --write; absent means zero games played."""
    if not ACTUALS.exists():
        return []
    with ACTUALS.open(newline='') as source:
        return list(csv.DictReader(source))


def apply_actuals(rows, actuals):
    """Board rows plus actual games/FP per game; unknown names become IN-SEASON ADD rows."""
    by_name = {a['name']: a for a in actuals}
    merged = []
    for row in rows:
        row = dict(row)
        actual = by_name.pop(row['name'], None)
        if actual and int(actual['games']):
            row['games'], row['actual_ppg'] = int(actual['games']), float(actual['actual_ppg'])
            row['through'] = actual['through']
        merged.append(row)
    for i, a in enumerate(by_name.values(), len(rows) + 1):
        merged.append(dict(
            name=a['name'], original_rank=float(i), gp=float(ADD_GP), ppg=float(a['prior_ppg']),
            espn_delta=0.0, ecr=None, ecr_sd=None, ecr_best='', ecr_worst='', cluster=0.5,
            positions=a['positions'], sleeper_rank=None, injury_status=a['injury_status'],
            notes='IN-SEASON ADD | ' + a['note'], draft_exclude='', ecr_review='',
            games=int(a['games']), actual_ppg=float(a['actual_ppg']), prior_k=float(a['prior_k']),
            through=a['through'],
            in_season_add=True))
    return merged


def season_actuals(rows, logs, last_logs, pool):
    """Actual records for board players and qualifying non-board players. No network.

    logs/last_logs: game_logs() for this and the previous season; pool: Sleeper
    /players/nba. An add needs >= ADD_MIN_GAMES games, an NBA team, and both
    actual and blended FP/g above the board's blended replacement level.
    """
    import draft  # local: draft.py is only needed for name matching
    by_name = draft.name_index(pool)
    board = {}
    for row in rows:
        pid = by_name.get(draft.norm(row['name']))
        if pid:
            board[pid] = row['name']

    def record(name, games, **extra):
        return dict(name=name, games=len(games), actual_ppg=f'{sum(g[2] for g in games) / len(games):.4f}',
                    through=max(g[0] for g in games), **extra)

    actuals = [record(name, logs[pid]) for pid, name in board.items() if pid in logs]
    _, replacement = rank_players(apply_actuals(rows, actuals))
    names = {r['name'] for r in rows}
    for pid, games in sorted(logs.items()):
        player = pool.get(pid) or {}
        name = player.get('full_name')
        if pid in board or name in names or not name or not player.get('team') or len(games) < ADD_MIN_GAMES:
            continue
        last = last_logs.get(pid, [])
        if len(last) >= 10:
            prior, k = sum(g[2] for g in last) / len(last), BLEND_K
            note = f'prior = last season {prior:.1f}/g in {len(last)} G'
        else:
            prior, k = NO_PRIOR_PPG, NO_PRIOR_K
            note = f'no prior season; prior = league mean {prior:.1f}/g'
        actual = sum(g[2] for g in games) / len(games)
        if actual <= replacement or blend(prior, dict(games=len(games), actual_ppg=actual, prior_k=k)) <= replacement:
            continue
        actuals.append(record(name, games, prior_ppg=f'{prior:.4f}', prior_k=k,
                              positions='/'.join(player.get('fantasy_positions') or []),
                              injury_status=player.get('injury_status') or '', note=note))
    return actuals


def strip_actuals(rows):
    return [dict(r, games=0) for r in rows if not r.get('in_season_add')]


def rank_players(rows, cluster_override=None, expert_scale=1):
    projected = [r for r in rows if r['ppg'] is not None and not r['draft_exclude']]
    # A 10-team, 14-player league rosters 140 players. This is a rough
    # waiver baseline, not a position-specific or team-specific replacement.
    by_ppg = sorted((blend(r['ppg'], r) for r in projected), reverse=True)
    replacement_ppg = by_ppg[140]
    bench_surplus, _ = week_value(by_ppg[90], 82, 0.5, replacement_ppg)
    espn_curve = sorted((r['ppg'] - r['espn_delta'] for r in projected
                         if not r.get('in_season_add')), reverse=True)
    results = []
    for source in rows:
        row = dict(source)
        row['weight'] = 0.0
        row['q'] = 0.0
        row['value'] = 0.0
        if row['ppg'] is not None and not row['draft_exclude']:
            cluster = row['cluster'] if cluster_override is None else cluster_override
            row['calibrated_ppg'] = row['ppg']
            if row['ecr'] is not None:
                # Translate expert rank into ESPN-equivalent points first,
                # then restore THIS player's custom-scoring premium.
                prior = percentile_score(espn_curve, row['ecr']) + row['espn_delta']
                row['weight'] = expert_scale * expert_weight(row['ecr_sd'])
                correction = row['weight'] * (prior - row['ppg'])
                row['calibrated_ppg'] += max(-2, min(2, correction))
            # The ECR-calibrated projection is the prior; actual games pull it toward results.
            row['prior_ppg'] = row['calibrated_ppg']
            row['calibrated_ppg'] = blend(row['prior_ppg'], row)
            surplus, row['q'] = week_value(row['calibrated_ppg'], row['gp'], cluster, replacement_ppg)
            bench_cost = (1 - row['q']) * bench_surplus if row['injury_status'] == 'Out' else 0
            row['value'] = max(0, surplus - bench_cost)
        else:
            # Excluded and unprojected records have no draft value.
            row['calibrated_ppg'] = 0.0
        results.append(row)
    results.sort(key=lambda r: (bool(r['draft_exclude']), r['ppg'] is None, -r['value'],
                               -r['q'] * r['calibrated_ppg'],
                               r['ecr'] or 999, r['original_rank']))
    tier = 1
    anchor = results[0]['value']
    for rank, row in enumerate(results, 1):
        if anchor - row['value'] > 2:
            tier += 1
            anchor = row['value']
        row['rank'] = rank
        row['tier'] = tier
    if any(r.get('games') for r in rows):
        # Expert-gap reviews judge the frozen projections, so they use the prior-only rank.
        prior_rank = {r['name']: r['rank'] for r in rank_players(strip_actuals(rows))[0]}
        for row in results:
            row['prior_rank'] = prior_rank.get(row['name'])
    return results, replacement_ppg


def expert_outliers(rows):
    """Review both directions of a 20-place gap involving a draftable top-140 player."""
    return [r for r in rows if not r['draft_exclude'] and r['ecr'] is not None
            and min(r.get('prior_rank') or r['rank'], r['ecr']) <= 140
            and abs((r.get('prior_rank') or r['rank']) - r['ecr']) >= 20]


def require_expert_reviews(rows):
    missing = [r['name'] for r in expert_outliers(rows) if not r['ecr_review'].strip()]
    if missing:
        raise ValueError('Unreviewed expert discrepancies: ' + ', '.join(missing)
                         + '. Run --audit; check inputs and record ecr_review before rebuilding.')


def board_text(rows, replacement):
    outliers = {r['name'] for r in expert_outliers(rows)}
    lines = [
        '# Ranked by weekly lock-in surplus under league scoring; rebuild_board.py --write.',
        f'# V = expected locked weekly score above a healthy {replacement:.1f}/game replacement (one game kept per week).',
        '# T = two-point value tier. ECR = ESPN expert consensus (rank semantics unverified). Season FP are reference only.',
        '# Use Sleeper positions and roster needs WITHIN tiers; no fixed center premium.',
    ]
    played = [r for r in rows if r.get('games')]
    if played:
        lines.append(f'# In-season blend: FP/g -> prior + n/(n+{BLEND_K:g})*(actual - prior) after n games '
                     f'({len(played)} players, games through {max(r["through"] for r in played)}); '
                     'board-actuals.csv.')
    for row in rows:
        ecr = str(int(row['ecr'])) if row['ecr'] else '?'
        if row['draft_exclude']:
            note = 'DO NOT DRAFT | ' + row['draft_exclude']
        elif row['ppg'] is None:
            note = f'NO PROJECTION | ECR {ecr} | ' + row['notes']
        else:
            note = (f"T{row['tier']} | V+{row['value']:.1f}/wk | "
                    f"{row['ppg']:.1f}/g | "
                    # The ECR-calibrated prior behind V, when it prints differently from the raw projection
                    # (so they differ by >= 0.05); gm.py reads it.
                    + (f"cal {row['prior_ppg']:.1f}/g | " if f"{row['prior_ppg']:.1f}" != f"{row['ppg']:.1f}" else '')
                    + f"ECR {ecr} | "
                    + (f"{row['games']} G {row['actual_ppg']:.1f}/g -> {row['calibrated_ppg']:.1f}/g | "
                       if row.get('games') else '') +
                    f"{int(row['gp'])} GP | season {round(row['gp'] * row['ppg'])} FP")
            if row['notes']:
                note += ' | ' + row['notes']
            if row['ecr_sd'] is not None and row['ecr_sd'] >= 20:
                note += ' | ECR disagreement: reduced weight'
        if row['name'] in outliers:
            note += ' | ECR review: ' + (row['ecr_review'] or 'UNREVIEWED')
        if not row['draft_exclude'] and row['injury_status'] == 'Out':
            note += ' | OUT uses bench, not IR'
        lines.append(row['name'] + '  # ' + note)
    return '\n'.join(lines) + '\n'


def cache_self_test():
    import io
    import tempfile
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / '.cache').mkdir()
        old = [{'player_id': '1', 'date': '2026-10-24', 'stats': {'sp': 1, 'pts': 10}}]
        complete = old + [dict(old[0], date='2026-10-25')]
        (root / '.cache' / f'stats-{SEASON}-01.json').write_text(json.dumps(old))
        (root / '.cache' / f'stats-{SEASON}-02.json').write_text(json.dumps(old))
        with patch(__name__ + '.HERE', root), patch.object(urllib.request, 'urlopen',
                                                          return_value=io.StringIO(json.dumps(complete))):
            result = fetch_week(SEASON, 1)
        assert len(result) == 2, 'Later-week data must not freeze a partial preceding week'
        historical = root / '.cache' / f'stats-{SEASON - 1}-01.json'
        historical.write_text(json.dumps(complete))
        with patch(__name__ + '.HERE', root), patch.object(urllib.request, 'urlopen', side_effect=AssertionError('network')):
            assert fetch_week(SEASON - 1, 1) == complete


def movers_self_test():
    import contextlib
    import io
    frozen = load_inputs()
    unprojected = next(r['name'] for r in frozen if r['ppg'] is None)
    ranked, replacement = rank_players(apply_actuals(frozen, [
        dict(name=unprojected, games=1, actual_ppg=30, through='2026-10-21')]))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        print_movers(ranked)
    assert unprojected not in out.getvalue()
    assert unprojected + '  # NO PROJECTION' in board_text(ranked, replacement)


def self_test():
    cache_self_test()
    movers_self_test()
    lv = lock_values(45)
    assert lv[0] == 0 and abs(lv[1] - 45) < 0.5 and all(a < b for a, b in zip(lv, lv[1:]))
    assert 1.15 < healthy_lock(45) / 45 < 1.35
    # Healthy replacement-level surplus is zero within 1e-9 (Gate G7)
    assert abs(week_value(27.1, 82, 0.5, 27.1)[0]) < 1e-9
    assert abs(week_value(45, 82, 0.5, 27.1)[1] - 1) < 1e-9
    # Whole-week vs dispersed absences and lost Lock-In opportunities
    assert abs(week_value(45, 41, 1, 27.1)[0] - week_value(45, 82, 1, 27.1)[0] / 2) < 1e-9
    assert week_value(45, 60, 0.15, 27.1)[0] < week_value(45, 82, 0.15, 27.1)[0]
    assert week_value(45, 60, 0.15, 27.1)[0] > week_value(45, 60, 0.85, 27.1)[0]
    # Expected GP conservation across whole-week and dispersed miss rates
    for gp, c in ((60, 0.15), (59, 0.65), (73, 0.5), (55, 1.0)):
        ww = c * (1 - gp / 82)
        gm = (1 - c) * (1 - gp / 82) / (1 - ww)
        assert abs((1 - ww) * (1 - gm) - gp / 82) < 1e-9
    assert expert_weight(0) == 0.25
    assert expert_weight(50) < 0.025
    assert percentile_score([60, 50, 40], 1.5) == 55
    assert percentile_score([60, 50, 40], 99) == 40
    samples = [dict(name='Optimistic', rank=40, ecr=70, draft_exclude='', ecr_review=''),
               dict(name='Pessimistic', rank=170, ecr=120, draft_exclude='', ecr_review='Role checked'),
               dict(name='Deep', rank=200, ecr=240, draft_exclude='', ecr_review=''),
               dict(name='Unsigned', rank=272, ecr=114, draft_exclude='Waived', ecr_review='')]
    assert [r['name'] for r in expert_outliers(samples)] == ['Optimistic', 'Pessimistic']
    try:
        require_expert_reviews(samples)
    except ValueError as error:
        assert 'Optimistic' in str(error) and 'Pessimistic' not in str(error)
    else:
        raise AssertionError('Unreviewed optimistic projection was accepted')
    samples[0]['ecr_review'] = 'Recovery assumptions corrected'
    require_expert_reviews(samples)
    frozen = load_inputs()
    rows = apply_actuals(frozen, load_actuals())
    ranked, replacement = rank_players(rows)
    require_expert_reviews(ranked)
    assert abs(week_value(replacement, 82, 0.5, replacement)[0]) < 1e-9
    assert len(ranked) == len(rows)
    assert all(r['value'] >= 0 for r in ranked)
    assert all(r['weight'] <= 0.25 for r in ranked)
    assert all(abs(r['prior_ppg'] - r['ppg']) <= 2.000001
               for r in ranked if r['ppg'] is not None and not r['draft_exclude'])
    assert all(r['value'] == 0 for r in ranked if r['draft_exclude'])
    assert 'OUT uses bench' not in board_text(
        [dict(ranked[-1], draft_exclude='Waived', injury_status='Out')], replacement)
    # Excluded players must not affect replacement, calibration, or anyone else's rank.
    inflated = [dict(r, ppg=1000, espn_delta=0) if r['draft_exclude'] else dict(r) for r in rows]
    inflated_ranked, inflated_replacement = rank_players(inflated)
    assert inflated_replacement == replacement
    assert [(r['name'], r['value']) for r in inflated_ranked] == [(r['name'], r['value']) for r in ranked]
    assert sum(r['ppg'] is None for r in ranked) == sum(r['ppg'] is None for r in rows)
    assert board_text(ranked, replacement) == board_text(*rank_players(rows))
    assert (HERE / 'board.txt').read_text() == board_text(ranked, replacement), 'Saved board is stale; rebuild it'
    blend_self_test(frozen)
    print('ok: lock-in stopping, replacement, GP conservation, exclusions, expert review, saved board, '
          'in-season blend')


def blend_self_test(frozen):
    """Zero-game identity, blend arithmetic, and in-season-add filtering on fixtures (offline)."""
    base = board_text(*rank_players(frozen))
    zero = [dict(name=frozen[0]['name'], games='0', actual_ppg='99', through='2026-10-20')]
    assert board_text(*rank_players(apply_actuals(frozen, []))) == base
    assert board_text(*rank_players(apply_actuals(frozen, zero))) == base
    assert blend(40.0, {}) == 40.0 and blend(40.0, dict(games=0, actual_ppg=99)) == 40.0
    assert abs(blend(40.0, dict(games=5, actual_ppg=50.0)) - (5 * 50 + BLEND_K * 40) / (5 + BLEND_K)) < 1e-12
    assert abs(blend(20.0, dict(games=3, actual_ppg=40.0, prior_k=2.5)) - (120 + 50) / 5.5) < 1e-12
    played = [dict(name='Nikola Jokic', games='10', actual_ppg='60.0', through='2026-11-09')]
    ranked, _ = rank_players(apply_actuals(frozen, played))
    jokic = next(r for r in ranked if r['name'] == 'Nikola Jokic')
    prior = next(r for r in rank_players(frozen)[0] if r['name'] == 'Nikola Jokic')['calibrated_ppg']
    assert jokic['prior_ppg'] == prior and jokic['prior_rank'] == 1
    assert abs(jokic['calibrated_ppg'] - (prior + 10 / (10 + BLEND_K) * (60 - prior))) < 1e-12
    assert '10 G 60.0/g -> ' in board_text(ranked, _) and '# In-season blend' in board_text(ranked, _)
    # The "-> X/g" text is the FP/g behind V (ECR-calibrated, then blended); gm.py reads it.
    # Banchero's ECR shifts his prior by ~1.5/g, so blending the raw projection prints a different number.
    ranked, _ = rank_players(apply_actuals(frozen, [dict(name='Paolo Banchero', games='4', actual_ppg='40.0',
                                                         through='2026-10-27')]))
    paolo = next(r for r in ranked if r['name'] == 'Paolo Banchero')
    assert abs(paolo['prior_ppg'] - paolo['ppg']) > 1 and f"4 G 40.0/g -> {paolo['calibrated_ppg']:.1f}/g |" in board_text(ranked, _)
    # Unblended, " | cal X/g" carries the calibrated FP/g (regression: gm.py read the raw 47.6 for Banchero);
    # it is omitted when the two print the same (calibration moved the projection by < 0.05).
    ranked, _ = rank_players(frozen)
    lines = dict(line.split('  # ', 1) for line in board_text(ranked, _).splitlines() if '  # ' in line)
    paolo = next(r for r in ranked if r['name'] == 'Paolo Banchero')
    assert f"| {paolo['ppg']:.1f}/g | cal {paolo['prior_ppg']:.1f}/g | ECR" in lines['Paolo Banchero'], lines['Paolo Banchero']
    same = [r['name'] for r in ranked if r['ppg'] is not None and not r['draft_exclude']
            and f"{r['prior_ppg']:.1f}" == f"{r['ppg']:.1f}"]
    assert same and not any('cal ' in lines[n] for n in same), same
    # In-season adds: >= 3 games, on an NBA team, actual and blended FP/g above replacement.
    def games(n, fp):
        return [(f'2026-10-{20 + i}', str(i), fp, 30.0) for i in range(n)]
    pool = {'1': dict(full_name='Nikola Jokic', team='DEN', active=True, fantasy_positions=['C']),
            '2': dict(full_name='Rookie Breakout', team='SAC', active=True, fantasy_positions=['SG', 'SF'],
                      injury_status='Questionable'),
            '3': dict(full_name='Two Games', team='SAC', active=True),
            '4': dict(full_name='Free Agent', team=None, active=True),
            '5': dict(full_name='Low Scorer', team='SAC', active=True),
            '6': dict(full_name='Hot Veteran', team='SAC', active=True)}
    logs = {'1': games(4, 70.0), '2': games(3, 45.0), '3': games(2, 60.0), '4': games(4, 50.0),
            '5': games(4, 20.0), '6': games(3, 35.0)}
    last_logs = {'6': games(20, 15.0)}  # 15 + 3/9.5 * 20 = 21.3/g: below replacement despite 35/g
    actuals = season_actuals(frozen, logs, last_logs, pool)
    assert [a['name'] for a in actuals] == ['Nikola Jokic', 'Rookie Breakout'], actuals
    assert actuals[0]['games'] == 4 and actuals[1]['prior_k'] == NO_PRIOR_K
    ranked, replacement = rank_players(apply_actuals(frozen, actuals))
    add = next(r for r in ranked if r['name'] == 'Rookie Breakout')
    assert add['value'] > 0 and add['rank'] < len(frozen) and add['positions'] == 'SG/SF'
    text = board_text(ranked, replacement)
    assert 'Rookie Breakout  # T' in text and 'IN-SEASON ADD | no prior season' in text
    assert board_text(*rank_players(apply_actuals(frozen, actuals))) == text


def print_movers(ranked, limit=10):
    moved = [r for r in ranked if r.get('games') and r['ppg'] is not None
             and not r['draft_exclude'] and not r.get('in_season_add')]
    moved.sort(key=lambda r: r['rank'] - r['prior_rank'])
    for label, group in (('Risers', moved[:limit]), ('Fallers', moved[::-1][:limit])):
        print(label + ' (frozen rank -> blended rank):')
        for r in group:
            print(f"  {r['name']:<26} {r['prior_rank']:3} -> {r['rank']:3}  "
                  f"{r['prior_ppg']:.1f}/g -> {r['calibrated_ppg']:.1f}/g ({r['games']} G at {r['actual_ppg']:.1f})")
    adds = [r for r in ranked if r.get('in_season_add')]
    print(f'In-season adds ({len(adds)}):')
    for r in adds:
        print(f"  {r['rank']:3} {r['name']:<26} V+{r['value']:.1f} {r['games']} G at {r['actual_ppg']:.1f}/g "
              f"-> {r['calibrated_ppg']:.1f}/g | {r['notes']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--audit', action='store_true', help='show major expert discrepancies and their review')
    parser.add_argument('--blend', action='store_true',
                        help='refetch this season\'s Sleeper game logs and blend them into FP/g')
    parser.add_argument('--season', type=int, default=SEASON,
                        help='with --blend: replay another season as a preview (never written)')
    parser.add_argument('--through-week', type=int, default=25, help='with --blend: last fantasy week used')
    args = parser.parse_args()
    if args.test:
        self_test()
        return
    if args.write and args.blend and args.season != SEASON:
        raise SystemExit(f'REFUSING: --season {args.season} is a preview; only {SEASON} is written')
    target = HERE / 'board.txt'
    digest = hashlib.sha256(target.read_bytes()).digest()
    rows = load_inputs()
    if args.blend:
        import draft
        logs = game_logs(season_weeks(args.season, args.through_week))
        last_logs = game_logs(season_weeks(args.season - 1))
        actuals = season_actuals(rows, logs, last_logs, draft.players())
        print(f'{args.season} weeks 1-{args.through_week}: {len(logs)} players with games; '
              f'{len(actuals)} actual records')
    else:
        actuals = load_actuals()
    ranked, replacement = rank_players(apply_actuals(rows, actuals))
    if args.blend:
        if not actuals:
            print('No games played yet: blended board equals the frozen board:',
                  board_text(ranked, replacement) == board_text(*rank_players(rows)))
        else:
            print_movers(ranked)
    if args.audit:
        for row in expert_outliers(ranked):
            print(f"{row['name']}: board {row.get('prior_rank') or row['rank']}, ECR {int(row['ecr'])}, "
                  f"expert range {row['ecr_best']}-{row['ecr_worst']} | "
                  + (row['ecr_review'] or 'UNREVIEWED'))
    if args.audit or args.write:
        try:
            require_expert_reviews(ranked)
        except ValueError as error:
            raise SystemExit('REFUSING: ' + str(error)) from error
    if args.audit and not args.write:
        return
    print(f'Replacement baseline: {replacement:.1f} FP/game; {len(ranked)} players')
    for row in ranked[:60]:
        print(f"{row['rank']:3} T{row['tier']:<2} {row['name']:<26} "
              f"V+{row['value']:4.1f} old {int(row['original_rank']):3} "
              f"ECR {int(row['ecr']) if row['ecr'] else '?'}")
    if args.write:
        if hashlib.sha256(target.read_bytes()).digest() != digest:
            raise SystemExit('REFUSING: board.txt changed during rebuild')
        if args.blend:
            with ACTUALS.with_suffix('.csv.tmp').open('w', newline='') as out:
                writer = csv.DictWriter(out, ACTUAL_FIELDS)
                writer.writeheader()
                writer.writerows(actuals)
            os.replace(ACTUALS.with_suffix('.csv.tmp'), ACTUALS)
            print(f'Wrote {ACTUALS.name}')
        temporary = target.with_suffix('.txt.tmp')
        temporary.write_text(board_text(ranked, replacement))
        os.replace(temporary, target)
        print('Wrote board.txt')


if __name__ == '__main__':
    main()
