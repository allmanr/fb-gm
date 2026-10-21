#!/usr/bin/env python3
"""Reproduce WEEK_GAMES, CV_A, CV_B and the in-season blend constants in rebuild_board.py
from Sleeper NBA game logs (cached in .cache/ by rebuild_board.fetch_week).

Source:  https://api.sleeper.com/stats/nba/2025/{1..25}?season_type=regular
Season:  2025-26 NBA regular season (weeks 1..25)
Scoring: league custom points (pts 1, reb 1.5, ast 2, stl 2.5, blk 2.5, to -2,
         fgm 2, fga -1, ftm 1, ftmi -1, tpm 1)
Filters:
  - WEEK_GAMES: distinct game_id per (week, team) across team and opponent fields.
  - CV fit: player game rows (numeric player_id) with seconds played sp > 0;
    OLS of population CV (pstdev / mean) on ln(mean) across players with
    >= 40 games played and >= 25.0 FP/game (n = 151 players).
  - Blend fit (--fit-blend): rest-of-season FP/g after a player's first n = 3, 5, 10, 20
    games (>= 10 games left) predicted by prior + n/(n+k)(actual - prior). Prior = the
    player's 2024-25 FP/g (>= 10 GP, >= 20 FP/g), a proxy for a pre-season projection;
    players with no prior season get a fitted constant mean. 2024-25 (prior 2023-24)
    is the out-of-sample check. Grid over k in half-game steps.

Usage:
  python3 fit_lockin.py
  python3 fit_lockin.py --fit-blend
  python3 fit_lockin.py --test
"""
import argparse
from collections import Counter, defaultdict
import math
import statistics

import rebuild_board

SCORING = rebuild_board.SCORING
MIN_GAMES = 40
MIN_PPG = 25.0


def fit_from_sleeper():
    weeks_data = rebuild_board.season_weeks(2025)
    assert len(weeks_data) == 25, sorted(weeks_data)
    team_week_games = defaultdict(set)
    for week, rows in sorted(weeks_data.items()):
        for row in rows:
            gid = row.get('game_id')
            for team in (row.get('team'), row.get('opponent')):
                if gid and team:
                    team_week_games[(week, team)].add(gid)
    player_games = {pid: [g[2] for g in games]
                    for pid, games in rebuild_board.game_logs(weeks_data).items()}

    week_games = dict(sorted(Counter(len(gids) for gids in team_week_games.values()).items()))

    xs, ys = [], []
    for fps in player_games.values():
        if len(fps) < MIN_GAMES:
            continue
        mean = sum(fps) / len(fps)
        if mean < MIN_PPG:
            continue
        cv = statistics.pstdev(fps) / mean
        xs.append(math.log(mean))
        ys.append(cv)

    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cv_b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    cv_a = my - cv_b * mx
    return week_games, cv_a, cv_b, len(xs)


BLEND_NS = (3, 5, 10, 20)
PRIOR_MIN_GP = 10  # prior-season games needed to use that season's FP/g as the prior
ROS_MIN_GP = 10    # rest-of-season games needed for a stable target
K_GRID = [i / 2 for i in range(161)]  # 0..80 games
BLEND_MIN_PRIOR = 20.0  # board-relevant players: prior-season FP/g >= 20


def season_logs(season):
    return rebuild_board.game_logs(rebuild_board.season_weeks(season))


def blend_cases(season, min_prior_ppg=0.0):
    """Per n: (obs FP/g, obs min/g, obs FP/min, prior FP/g or None, prior min/g, target ROS FP/g).

    Prior = the player's previous-season FP/g (>= PRIOR_MIN_GP games), a proxy
    for a pre-season projection. Players without one get prior None.
    """
    logs = season_logs(season)
    prior = {pid: (sum(g[2] for g in games) / len(games), sum(g[3] for g in games) / len(games))
             for pid, games in season_logs(season - 1).items() if len(games) >= PRIOR_MIN_GP}
    cases = {}
    for n in BLEND_NS:
        cases[n] = []
        for pid, games in logs.items():
            if len(games) < n + ROS_MIN_GP:
                continue
            head, rest = games[:n], games[n:]
            fp, minutes = sum(g[2] for g in head), sum(g[3] for g in head)
            p_fp, p_min = prior.get(pid, (None, None))
            if p_fp is not None and p_fp < min_prior_ppg:
                continue
            cases[n].append((fp / n, minutes / n, fp / max(minutes, 1), p_fp, p_min,
                             sum(g[2] for g in rest) / len(rest)))
    return cases


def rmse(errors):
    errors = list(errors)
    return math.sqrt(sum(e * e for e in errors) / len(errors))


def blend_rmse(cases, k):
    """RMSE of prior + n/(n+k) * (actual - prior) over players with a prior."""
    return rmse(t - (p + n / (n + k) * (a - p))
                for n, rows in cases.items() for a, _, _, p, _, t in rows if p is not None)


def minutes_rmse(cases, k_min, k_rate):
    """Blend minutes/g and FP/minute separately (both priors from the previous season)."""
    def pred(n, a_min, a_rate, p_fp, p_min):
        minutes = p_min + n / (n + k_min) * (a_min - p_min)
        rate = p_fp / p_min + n / (n + k_rate) * (a_rate - p_fp / p_min)
        return minutes * rate
    return rmse(t - pred(n, m, r, p, pm)
                for n, rows in cases.items() for _, m, r, p, pm, t in rows if p is not None)


def no_prior_fit(cases, k):
    """Best constant prior mean m for players without one at shrinkage k, and its RMSE."""
    rows = [(n / (n + k), a, t) for n, rs in cases.items() for a, _, _, p, _, t in rs if p is None]
    m = sum(t - w * a for w, a, t in rows) / sum(1 - w for w, _, _ in rows) if k else 0.0
    return m, rmse(t - (w * a + (1 - w) * m) for w, a, t in rows)


def fit_blend(season=2025, check_season=2024, min_prior_ppg=BLEND_MIN_PRIOR):
    report = {}
    for s in (season, check_season):
        cases = blend_cases(s, min_prior_ppg)
        best_k = min(K_GRID, key=lambda k: blend_rmse(cases, k))
        per_n = {}
        for n, rows in cases.items():
            one = {n: rows}
            with_prior = [r for r in rows if r[3] is not None]
            per_n[n] = dict(
                players=len(with_prior),
                prior_only=rmse(t - p for _, _, _, p, _, t in with_prior),
                actual_only=rmse(t - a for a, _, _, _, _, t in with_prior),
                best_k=min(K_GRID, key=lambda k: blend_rmse(one, k)),
                pooled=blend_rmse(one, best_k))
            per_n[n]['best_k_rmse'] = blend_rmse(one, per_n[n]['best_k'])
        grid = [(minutes_rmse(cases, km, kr), km, kr)
                for km in range(0, 61, 2) for kr in range(0, 61, 2)]
        no_prior_k = min(K_GRID[1:], key=lambda k: no_prior_fit(cases, k)[1])
        report[s] = dict(cases=cases, k=best_k, rmse=blend_rmse(cases, best_k), per_n=per_n,
                         prior_only=blend_rmse(cases, math.inf), actual_only=blend_rmse(cases, 0),
                         minutes=min(grid), no_prior=(no_prior_k,) + no_prior_fit(cases, no_prior_k),
                         no_prior_players={n: sum(r[3] is None for r in rows) for n, rows in cases.items()})
    report['check_at_fit_k'] = blend_rmse(report[check_season]['cases'], report[season]['k'])
    k0, m0 = report[season]['no_prior'][:2]
    rows = [(n / (n + k0), a, t) for n, rs in report[check_season]['cases'].items()
            for a, _, _, p, _, t in rs if p is None]
    report['check_no_prior'] = rmse(t - (w * a + (1 - w) * m0) for w, a, t in rows)
    return report


def print_blend(report, season=2025, check_season=2024):
    for s in (season, check_season):
        r = report[s]
        print(f'{s}-{(s + 1) % 100:02d} (prior = {s - 1}-{s % 100:02d} FP/g): pooled k = {r["k"]}, RMSE {r["rmse"]:.2f} '
              f'(prior-only {r["prior_only"]:.2f}, actual-only {r["actual_only"]:.2f})')
        print('   n  players  prior-only  actual-only  blend@pooled-k  best-k(n)  RMSE@best-k')
        for n, d in r['per_n'].items():
            print(f'  {n:2}  {d["players"]:7}  {d["prior_only"]:10.2f}  {d["actual_only"]:11.2f}  '
                  f'{d["pooled"]:14.2f}  {d["best_k"]:9}  {d["best_k_rmse"]:11.2f}')
        mr, km, kr = r['minutes']
        print(f'  minutes x FP/min blend: k_min = {km}, k_rate = {kr}, RMSE {mr:.2f} (single-k {r["rmse"]:.2f})')
        k0, m0, e0 = r['no_prior']
        print(f'  no prior ({r["no_prior_players"]}): k = {k0}, league-mean prior m = {m0:.1f} FP/g, RMSE {e0:.2f}')
    print(f'{check_season} out-of-sample RMSE at the {season} k = {report[season]["k"]}: {report["check_at_fit_k"]:.2f}; '
          f'no-prior at the {season} k, m: {report["check_no_prior"]:.2f}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--fit-blend', action='store_true', help='fit in-season projection shrinkage k')
    parser.add_argument('--min-prior-ppg', type=float, default=BLEND_MIN_PRIOR)
    args = parser.parse_args()
    if args.fit_blend:
        print_blend(fit_blend(min_prior_ppg=args.min_prior_ppg))
        return

    week_games, cv_a, cv_b, n_players = fit_from_sleeper()
    print(f'WEEK_GAMES = {week_games}')
    print(f'CV_A = {cv_a:.4f}, CV_B = {cv_b:.4f} (n = {n_players} players)')

    if args.test:
        assert week_games == rebuild_board.WEEK_GAMES, (week_games, rebuild_board.WEEK_GAMES)
        assert abs(cv_a - rebuild_board.CV_A) <= 0.005, (cv_a, rebuild_board.CV_A)
        assert abs(cv_b - rebuild_board.CV_B) <= 0.005, (cv_b, rebuild_board.CV_B)
        assert n_players == 151, n_players
        print('ok: reproduced WEEK_GAMES exactly and CV_A, CV_B within 0.005')
        report = fit_blend()
        print_blend(report)
        k0, m0 = report[2025]['no_prior'][:2]
        assert report[2025]['k'] == rebuild_board.BLEND_K, (report[2025]['k'], rebuild_board.BLEND_K)
        assert k0 == rebuild_board.NO_PRIOR_K and abs(m0 - rebuild_board.NO_PRIOR_PPG) <= 0.05, (k0, m0)
        assert report[2025]['minutes'][0] > 0.98 * report[2025]['rmse'], 'minutes blend now wins clearly'
        print('ok: reproduced BLEND_K, NO_PRIOR_K, NO_PRIOR_PPG; minutes blend gains < 2%')


if __name__ == '__main__':
    main()
