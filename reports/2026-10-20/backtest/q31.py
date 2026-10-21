"""Issue #31: are fantasy-relevant players on bad teams out more in our playoff weeks (Mar 8-28)?

Players at 35+ FP/g with 25+ games in Nov 1 - Feb 14 (same season). Standings frozen at Feb 15 from Sleeper's
schedule results (no hindsight). Unit: a player-week whose team has 1+ game; "out" = he played none of them,
the whole-week absence Lock-In can't recover (V is surplus over a replacement, so an out week loses V).
Availability factor = (1 - out rate in playoff-window weeks) / (1 - out rate Nov-Feb weeks), so injuries the
board's GP already prices cancel. Also: how well an early-season bottom 10 (after N team games) predicts the
deadline bottom 10, which decides when trade.py may trust live standings.
Usage: python3 q31.py
"""
import random
from collections import defaultdict
from lib import _load_season, REPO  # noqa: F401 (REPO puts gm on sys.path)
import gm, trade

SEASONS = {'data24': 2024, 'data': 2025}


def standings(sched, until=None, n_games=None):
    """team -> win pct over complete games on or before until, or each team's first n_games."""
    w, g = defaultdict(int), defaultdict(int)
    nba = set(trade.po_avail(sched))  # drops All-Star sides (codes vary by season)
    for x in sorted(sched, key=lambda x: x['date']):
        if x.get('status') != 'complete' or (until and x['date'] > until):
            continue
        h, a = x['home'], x['away']
        if None in (h.get('points'), a.get('points')) or not {h['team'], a['team']} <= nba:
            continue
        for t, won in ((h['team'], h['points'] > a['points']), (a['team'], a['points'] > h['points'])):
            if n_games is None or g[t] < n_games:
                g[t] += 1
                w[t] += won
    return {t: w[t] / g[t] for t in g}


def bottom(pct, n=10):
    return set(sorted(pct, key=pct.get)[:n])


def season(folder, y):
    rows = _load_season(folder)
    sched = gm.schedule(y)
    deadline = f'{y + 1}-02-15'
    bot = bottom(standings(sched, until=deadline))
    live = trade.po_avail(sched, until=deadline)  # the live code names the same deadline bottom 10
    assert {t for t, f in live.items() if f == trade.PO_AVAIL['bottom']} == bot, (sorted(bot), live)
    early = defaultdict(list)
    for w, d, t, g, p, s in rows:
        if f'{y}-11-01' <= d < deadline and s is not None:
            early[p].append(s)
    rel = {p for p, v in early.items() if len(v) >= 25 and sum(v) / len(v) >= 35}
    wk_min = defaultdict(lambda: '9999')
    for w, d, t, g, p, s in rows:
        wk_min[w] = min(wk_min[w], d)
    early_w = {w for w, d in wk_min.items() if f'{y}-11-01' <= d < deadline}
    po_w = {w for w, d in wk_min.items() if f'{y + 1}-03-08' <= d <= f'{y + 1}-03-24'}
    pw = defaultdict(lambda: [0, 0, None])  # (pid, week) -> [games, played, team]
    for w, d, t, g, p, s in rows:
        if p in rel and (w in early_w or w in po_w):
            c = pw[(p, w)]
            c[0] += 1
            c[1] += s is not None
            c[2] = t
    per = defaultdict(lambda: [0, 0, 0, 0])  # (group, pid) -> [early out, early weeks, po out, po weeks]
    for (p, w), c in pw.items():
        k = per[('bottom10' if c[2] in bot else 'rest', p)]
        i = 2 if w in po_w else 0
        k[i] += not c[1]
        k[i + 1] += 1
    out = {}
    for grp, inside in (('bottom10', True), ('rest', False)):
        for span, ws in (('early', early_w), ('po', po_w)):
            cells = [c for (p, w), c in pw.items() if w in ws and (c[2] in bot) == inside]
            games = [c for c in cells if c[1]]
            out[(grp, span)] = (sum(not c[1] for c in cells), len(cells),
                                sum(c[0] - c[1] for c in games), sum(c[0] for c in games))
    # early-season predictiveness of the deadline bottom 10
    hit = {n: len(bottom(standings(sched, n_games=n)) & bot) / 10 for n in (10, 15, 20, 30, 40)}
    return out, hit, sorted(po_w), len(rel), per


def main():
    pooled = defaultdict(lambda: [0, 0, 0, 0])  # (group, span) -> summed counts over seasons
    players = defaultdict(list)  # group -> per-player counts, both seasons
    for folder, y in SEASONS.items():
        out, hit, po_w, n, per = season(folder, y)
        for (grp, p), c in per.items():
            players[grp].append(c)
        print(f'{y}-{(y + 1) % 100:02d}: {n} players, playoff-window weeks {po_w}')
        for grp in ('bottom10', 'rest'):
            (eo, en, eg, egn), (po, pn, pg, pgn) = out[(grp, 'early')], out[(grp, 'po')]
            f = (1 - po / pn) / (1 - eo / en)
            print(f'  {grp:8s} out-weeks Nov-Feb {eo / en:5.1%} (n={en}) | Mar {po / pn:5.1%} (n={pn}) | '
                  f'factor {f:.2f} | in-week DNP {eg / egn:4.1%} -> {pg / pgn:4.1%}')
            for span in ('early', 'po'):
                pooled[(grp, span)] = [a + b for a, b in zip(pooled[(grp, span)], out[(grp, span)])]
        print('  deadline bottom-10 found after N team games: ' + ', '.join(f'{k}: {v:.0%}' for k, v in hit.items()))
    print('pooled:')
    for grp in ('bottom10', 'rest'):
        (eo, en, _, _), (po, pn, _, _) = pooled[(grp, 'early')], pooled[(grp, 'po')]
        rng, fs = random.Random(31), []
        for _ in range(2000):  # players resampled: a shutdown repeats across a player's weeks
            b = [sum(x) for x in zip(*rng.choices(players[grp], k=len(players[grp])))]
            if b[1] and b[3]:
                fs.append((1 - b[2] / b[3]) / (1 - b[0] / b[1]))
        fs.sort()
        print(f'  {grp:8s} factor {(1 - po / pn) / (1 - eo / en):.3f}  (out-weeks {eo / en:.1%} -> {po / pn:.1%}); '
              f'player bootstrap 95% CI {fs[50]:.2f}-{fs[1949]:.2f}, players {len(players[grp])}')


if __name__ == '__main__':
    main()
