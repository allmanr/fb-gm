"""Issue #22: does same-night slot reuse on staggered tips add enough to build? 2025-26 logs + ESPN tip times.

Baseline is gm.py's plan: base lineup by expected locked score, then gm.rotation (one roll per slot per day).
Reuse arm: after the baseline plan, each bench player who plays a day but feeds no slot (every eligible slot's
occupant plays that day) may take a slot whose rolls that day all tip at least GAP hours from his own tip
(an early starter or feeder, then him late; or him early, then the slot's late starter). Greedy by the
slot's gain in expected locked score, best FP/g first; a lower bound on a joint plan.
Scores: expected (the model, stop_value over the slot's rolls in tip order) and realized (the same lock lines
walked over the real box scores, DNP = 0, an unlocked slot keeps its last roll).
Rosters: (a) the Owner's live Sleeper roster replayed over 2025-26 weeks 1-25; (b) random 10-team leagues
drafted in 14 ten-rank bands of the top 140 by FP/g (40+ games), for wins (H2H + median, others on baseline).
Model inputs only: causal FP/g (q12.causal_ppg), gm.play_on DNP chances, fantasy_positions from the
players snapshot. No locks are known before the week (no blocked slots).

ponytail: game length is a fixed GAP (tip to next tip), not the real final time, so arms are given for
2.5/3/3.5 h; the Owner is assumed to make every swap (gain scales about linearly with the share made).
Usage: python3 q22.py [league_weeks=300] [seed=22]
"""
import datetime, json, os, random, sys, urllib.error
from collections import defaultdict
from lib import load, _load_season, player_snapshot, r1, HERE, REPO  # noqa: F401 (REPO puts gm on sys.path)
from q12 import causal_ppg
import draft, gm

D = load()
W = D['weeks']
SS = {p: (sum(s for v in ws.values() for _, s in v if s is not None), sum(s is not None for v in ws.values() for _, s in v))
      for p, ws in W.items()}
SS = {p: (t / g, g) for p, (t, g) in SS.items() if g}
ROWS = _load_season('data')
TEAM = {(p, d): t for w, d, t, g, p, s in ROWS}  # (pid, 'YYYY-MM-DD') -> team, only where he has a box-score row
WTEAM = {(p, w): t for w, d, t, g, p, s in ROWS}  # (pid, week) -> a team he had that week
# Tips key on his team that week where a night has no row for him, so a missing row can't hide a game.
POS = {p: v.get('fantasy_positions') or [] for p, v in player_snapshot().items()}
GAPS = (2.5, 3.0, 3.5)
TIPS = os.path.join(HERE, 'tips25')


def tips():
    """{(date, team): naive UTC tip} for every 2025-26 game date, ESPN scoreboard cached in tips25/."""
    os.makedirs(TIPS, exist_ok=True)
    out = {}
    for day in sorted({d for (_, d) in TEAM}):
        path = os.path.join(TIPS, f'{day}.json')
        if not os.path.exists(path):
            try:
                games = gm.espn_tips(gm.fetch(gm.ESPN.format(datetime.date.fromisoformat(day))))
            except (OSError, ValueError, KeyError, urllib.error.URLError) as e:
                print(f'no tips for {day}: {e}', file=sys.stderr)
                continue
            json.dump(games, open(path, 'w'))
        for aw, h, t in json.load(open(path)):
            utc = datetime.datetime.strptime(t, '%Y-%m-%dT%H:%MZ')
            out[(day, aw)] = out[(day, h)] = utc
    return out


TIP = tips()
CZ = {}


def ppg(p, w):
    if p not in CZ:
        CZ[p] = causal_ppg(p)
    return r1(CZ[p][w])


def week_inputs(roster, w):
    """-> days, games {p: {date: play chance}}, fpg, actual {(p, date): fp|None}, tip {(p, date): utc|None}."""
    games, fpg, actual, tip = {}, {}, {}, {}
    for p in roster:
        if w not in W.get(p, {}) or not POS.get(p):
            continue
        dates = [datetime.date.fromisoformat(d) for d, _ in W[p][w]]
        games[p] = {d: gm.play_on(d, set(dates)) for d in dates}
        fpg[p] = ppg(p, w)
        for d, s in W[p][w]:
            day = datetime.date.fromisoformat(d)
            actual[(p, day)] = s
            tip[(p, day)] = TIP.get((d, TEAM.get((p, d), WTEAM.get((p, w)))))
    days = sorted({d for g in games.values() for d in g})
    return days, games, fpg, actual, tip


def plans(roster, w):
    """-> (rolls per arm): arm 'base' and each GAP; rolls = {slot: [(day, tip, who)]} in chronological order."""
    days, games, fpg, actual, tip = week_inputs(roster, w)
    active = list(games)
    exp = {p: gm.wait_value(fpg[p], [games[p][d] for d in sorted(games[p])]) for p in active}
    base = gm.best_lineup([(p, POS[p]) for p in active], exp)
    bench = sorted((p for p in active if p not in base.values()), key=lambda p: -fpg[p])
    plan = gm.rotation(gm.SLOTS, base, bench, games, days, POS, fpg)
    rolls = {i: [] for i in range(len(gm.SLOTS))}
    for day in days:
        for i in rolls:
            who = gm.slot_who(day, base.get(i), {day: plan[day][i]} if i in plan[day] else {}, games, fpg)
            if who:
                rolls[i].append((day, tip[(who, day)], who))
    arms = {'base': rolls}
    for gap in GAPS:
        arms[gap] = reuse(rolls, plan, bench, games, days, fpg, tip, datetime.timedelta(hours=gap))
    return arms, games, fpg, actual


def value(rs, games, fpg):
    return gm.stop_value([[(fpg[who], games[who][day])] for day, _, who in rs])


def reuse(rolls, plan, bench, games, days, fpg, tip, gap):
    rolls = {i: list(rs) for i, rs in rolls.items()}
    for day in days:
        for p in bench:
            t = tip.get((p, day))
            if not t or day not in games[p] or p in plan[day].values():
                continue
            best, best_gain = None, 1e-9
            for i, rs in rolls.items():
                same = [x for x in rs if x[0] == day]
                if not same or not draft.SLOT_ELIGIBLE[gm.SLOTS[i]] & set(POS[p]):
                    continue  # an idle slot is the baseline's job (it fed it or nobody fits)
                if any(not x[1] or abs((x[1] - t).total_seconds()) < gap.total_seconds() for x in same):
                    continue
                new = sorted(rs + [(day, t, p)], key=lambda x: (x[0], x[1]))
                gain = value(new, games, fpg) - value(rs, games, fpg)
                if gain > best_gain:
                    best, best_gain = (i, new), gain
            if best:
                rolls[best[0]] = best[1]
    return rolls


def realized(rs, games, fpg, actual):
    """Walk the lock lines over real scores: lock when a played score reaches the value of the rest."""
    last = 0.0
    for k, (day, _, who) in enumerate(rs):
        s = actual[(who, day)]
        last = s or 0.0
        rest = rs[k + 1:]
        if s is not None and rest and s >= value(rest, games, fpg):
            return s
    return last


def team_week(roster, w):
    """-> {arm: (expected, realized, rolls)}."""
    arms, games, fpg, actual = plans(roster, w)
    return {a: (sum(value(rs, games, fpg) for rs in r.values()),
                sum(realized(rs, games, fpg, actual) for rs in r.values()),
                sum(len(rs) for rs in r.values())) for a, r in arms.items()}


def wins(tot, i):
    h2h = 1.0 if tot[i] > tot[i ^ 1] else 0.5 if tot[i] == tot[i ^ 1] else 0.0
    mid = sorted(tot)
    return h2h + (tot[i] > (mid[4] + mid[5]) / 2)


def boot(xs, rng, B=2000):
    """Mean and 95% CI of clustered rows: xs = [[values of one cluster]]."""
    def mean(cs):
        flat = [v for c in cs for v in c]
        return sum(flat) / len(flat)
    bs = sorted(mean([rng.choice(xs) for _ in xs]) for _ in range(B))
    return mean(xs), bs[int(.025 * B)], bs[int(.975 * B)]


def ours():
    cfg = json.load(open(os.path.join(REPO, 'private', 'config.json')))
    r = next(r for r in draft.get(f"/league/{cfg['league_id']}/rosters") if r['roster_id'] == gm.MY_ROSTER)
    roster = [p for p in r['players'] if p not in (r.get('reserve') or [])]
    rows = [team_week(roster, w) for w in range(1, 26)]
    have = [p for p in roster if p in W and POS.get(p)]
    print(f'Owner roster: {len(have)}/{len(roster)} active players have 2025-26 logs (the rest add nothing to either arm)')
    rng = random.Random(1)
    print(f"  baseline: expected {sum(r['base'][0] for r in rows) / 25:.1f} FP/wk, realized "
          f"{sum(r['base'][1] for r in rows) / 25:.1f}, rolls {sum(r['base'][2] for r in rows) / 25:.1f}/wk")
    for gap in GAPS:
        e = boot([[r[gap][0] - r['base'][0]] for r in rows], rng)
        x = boot([[r[gap][1] - r['base'][1]] for r in rows], rng)
        print(f'  gap {gap} h: +{sum(r[gap][2] - r["base"][2] for r in rows) / 25:.2f} rolls/wk; expected {e[0]:+.2f} FP/wk '
              f'[{e[1]:+.2f}, {e[2]:+.2f}]; realized {x[0]:+.2f} [{x[1]:+.2f}, {x[2]:+.2f}]')


def league(n=300, seed=22):
    rng = random.Random(seed)
    top = sorted((p for p, (m, g) in SS.items() if g >= 40 and POS.get(p)), key=lambda p: -SS[p][0])
    rows = {gap: {k: [] for k in ('rolls', 'exp', 'real', 'wins')} for gap in GAPS}  # per league-week: [per-team gains]
    base_e = []
    for _ in range(n):
        w = rng.randint(1, 25)
        pool = [p for p in top if w in W[p]][:140]
        bands = [rng.sample(pool[k * 10:(k + 1) * 10], 10) for k in range(14)]
        res = [team_week([bands[k][t] for k in range(14)], w) for t in range(10)]
        base_real = [r['base'][1] for r in res]
        base_e.append([r['base'][0] for r in res])
        for gap in GAPS:
            g = rows[gap]
            g['rolls'].append([r[gap][2] - r['base'][2] for r in res])
            g['exp'].append([r[gap][0] - r['base'][0] for r in res])
            g['real'].append([r[gap][1] - r['base'][1] for r in res])
            g['wins'].append([20 * (wins(base_real[:i] + [res[i][gap][1]] + base_real[i + 1:], i) - wins(base_real, i))
                              for i in range(10)])
    b = random.Random(7)
    print(f'Random leagues: {n} league-weeks x 10 teams; baseline expected {boot(base_e, b)[0]:.1f} FP/team-week')
    for gap in GAPS:
        g = rows[gap]
        out = [f"+{boot(g['rolls'], b)[0]:.2f} rolls/wk"]
        for k, unit in (('exp', 'FP/wk expected'), ('real', 'FP/wk realized'), ('wins', 'wins/20 wk')):
            m, lo, hi = boot(g[k], b)
            out.append(f'{m:+.2f} {unit} [{lo:+.2f}, {hi:+.2f}]')
        print(f'  gap {gap} h: ' + '; '.join(out))


if __name__ == '__main__':
    d = datetime.date(2025, 11, 4)
    a, b = datetime.datetime(2025, 11, 5, 0), datetime.datetime(2025, 11, 5, 3)
    rs = [(d, a, 'x')]
    g, f = {'x': {d: 0.92}, 'y': {d: 0.92}}, {'x': 40.0, 'y': 30.0}
    assert value(rs + [(d, b, 'y')], g, f) > value(rs, g, f)  # an extra late roll never hurts
    assert realized([(d, a, 'x'), (d, b, 'y')], g, f, {('x', d): 80.0, ('y', d): 10.0}) == 80.0  # locks a big early score
    assert realized([(d, a, 'x'), (d, b, 'y')], g, f, {('x', d): 5.0, ('y', d): None}) == 0.0  # passed, then a DNP
    print(f'tip times for {len({k[0] for k in TIP})} of {len({d for (_, d) in TEAM})} game dates', file=sys.stderr)
    args = [int(x) for x in sys.argv[1:]]
    ours()
    league(*args)
