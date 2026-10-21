"""Issue #26: does pooling bench scores across idle starters' slots (PR #27) beat the per-slot lane model?
2025-26 logs, replayed night by night on the real box scores.

Arms, all on the same base lineup (gm.best_lineup by expected locked score), no same-night reuse:
  lane   - gm.rotation without the seat-the-rest pass (the pre-#27 plan); each score judged on its own slot.
  seated - gm.rotation as merged (every bench player who fits an idle slot is seated); own-slot judging.
  pooled - the merged plan; the night's bench scores decided jointly by gm.joint_locks (one-hop reach,
           MOVE_COST per via lock), as `gm.py lock` does.
One replay serves every arm: each night the slot occupants post their real scores (DNP = 0, overwriting an
unlocked score), then every score is decided that night against the value of its slot's remaining planned
rolls (stop_value). A locked player's later planned rolls are dropped from every slot (he locks once). An
unlocked slot keeps its last roll. Hindsight: the best legal 9 of each player's best game (gm.best_lineup),
an upper bound no policy reaches without knowing the scores.
Rosters: (a) the Owner's live Sleeper roster over 2025-26 weeks 1-25; (b) random 10-team leagues from
ten-rank bands of the top 140 (q22's sampler), for wins (H2H + median, one team switched, others on lane).
ponytail: scores are decided on their game night, not deferred to the slot's next tip; a benched starter's
later games are not re-fed elsewhere (both conservative for pooled).
Usage: python3 q26.py [league_weeks=300] [seed=26]
"""
import random, sys
from unittest.mock import patch
import json, os
from q22 import W, POS, SS, REPO, week_inputs, boot, wins
import draft, gm


def plans(roster, w):
    days, games, fpg, actual, _ = week_inputs(roster, w)
    active = list(games)
    exp = {p: gm.wait_value(fpg[p], [games[p][d] for d in sorted(games[p])]) for p in active}
    base = gm.best_lineup([(p, POS[p]) for p in active], exp)
    bench = sorted((p for p in active if p not in base.values()), key=lambda p: -fpg[p])
    with patch.object(draft, 'fill_slots', lambda *a: {}):  # rotation's seat-the-rest pass only
        lane = gm.rotation(gm.SLOTS, base, bench, games, days, POS, fpg)
    seated = gm.rotation(gm.SLOTS, base, bench, games, days, POS, fpg)

    def rolls(plan):
        out = {i: [] for i in range(len(gm.SLOTS))}
        for day in days:
            for i in out:
                who = plan[day].get(i) or gm.slot_who(day, base.get(i), {}, games, fpg)
                if who:
                    out[i].append((day, who))
        return out
    return base, rolls(lane), rolls(seated), days, games, fpg, actual


def replay(base, rolls, days, games, fpg, actual, pooled, mean=None):
    """-> (locked + standing points, via locks). lanes: {lane: dict(slot, rolls, last)}; a via lock moves the
    feed's lane into the closed lane's slot. mean(p, day), when given, replaces fpg[p] in lock lines (q32)."""
    lanes = {i: dict(slot=i, rolls=list(rs), last=0.0) for i, rs in rolls.items()}
    total, vias, gone = 0.0, 0, set()
    value = lambda rs: gm.stop_value([[(mean(p, d) if mean else fpg[p], games[p][d])] for d, p in rs])
    for day in days:
        posted = {}
        for i, ln in lanes.items():
            ln['rolls'] = [(d, p) for d, p in ln['rolls'] if p not in gone]
            if ln['rolls'] and ln['rolls'][0][0] == day:
                p = ln['rolls'].pop(0)[1]
                ln['last'] = actual[(p, day)] or 0.0
                if actual[(p, day)] is not None:
                    posted[i] = p
        floor = {i: value(ln['rolls']) for i, ln in lanes.items()}
        feeds = {i: lanes[i]['last'] for i, p in posted.items() if p != base.get(i) and lanes[i]['rolls']}
        fits = lambda p, j: draft.SLOT_ELIGIBLE[gm.SLOTS[lanes[j]['slot']]] & set(POS[p])
        reach = {i: {j for j in lanes if j != i and all(fits(p, j) for _, p in lanes[i]['rolls'])} for i in feeds} if pooled else {}
        own = {i: lanes[i]['last'] for i in posted if i not in feeds}
        prices = {j: max(floor[j], own.get(j, 0.0)) for j in lanes}
        choice = gm.joint_locks(feeds, prices, reach)
        closed = set(choice.values()) - set(choice)
        for i, j in choice.items():
            total += lanes[i]['last']
            gone.add(posted[i])
            if j != i:
                vias += 1
                lanes[i].update(slot=lanes[j]['slot'], last=0.0)
                del lanes[j]
            else:
                del lanes[i]
        for i, s in own.items():
            if i not in closed and i in lanes and s >= floor[i] and lanes[i]['rolls']:
                total += s
                gone.add(posted[i])
                del lanes[i]
    return total + sum(ln['last'] for ln in lanes.values()), vias


def hindsight(roster, w):
    _, games, fpg, actual, _ = week_inputs(roster, w)
    best = {p: max([actual[(p, d)] or 0.0 for d in games[p]] or [0.0]) for p in games}
    return sum(best[p] for p in gm.best_lineup([(p, POS[p]) for p in games], best).values())


def team_week(roster, w):
    base, lane, seated, days, games, fpg, actual = plans(roster, w)
    out = {'lane': replay(base, lane, days, games, fpg, actual, False),
           'seated': replay(base, seated, days, games, fpg, actual, False),
           'pooled': replay(base, seated, days, games, fpg, actual, True)}
    out['hindsight'] = (hindsight(roster, w), 0)
    out['rolls'] = (sum(map(len, lane.values())), sum(map(len, seated.values())))
    return out


ARMS = ('seated', 'pooled')


def ours():
    cfg = json.load(open(os.path.join(REPO, 'private', 'config.json')))
    r = next(r for r in draft.get(f"/league/{cfg['league_id']}/rosters") if r['roster_id'] == gm.MY_ROSTER)
    roster = [p for p in r['players'] if p not in (r.get('reserve') or [])]
    rows = [team_week(roster, w) for w in range(1, 26)]
    rng = random.Random(1)
    m = lambda k: sum(r[k][0] for r in rows) / 25
    print(f"Owner roster, 2025-26 weeks 1-25: lane {m('lane'):.1f} FP/wk, hindsight {m('hindsight'):.1f}; rolls/wk "
          f"{sum(r['rolls'][0] for r in rows) / 25:.1f} lane, {sum(r['rolls'][1] for r in rows) / 25:.1f} seated")
    for a in ARMS:
        x = boot([[r[a][0] - r['lane'][0]] for r in rows], rng)
        share = (m(a) - m('lane')) / (m('hindsight') - m('lane'))
        print(f"  {a}: {m(a):.1f} FP/wk, {x[0]:+.2f} vs lane [{x[1]:+.2f}, {x[2]:+.2f}]; via locks "
              f"{sum(r[a][1] for r in rows) / 25:.2f}/wk; closes {100 * share:.1f}% of lane's gap to hindsight")
    worse = sorted(((r['pooled'][0] - r['lane'][0], w) for w, r in enumerate(rows, 1)))[:3]
    print("  pooled's worst weeks vs lane: " + ", ".join(f"w{w} {d:+.1f}" for d, w in worse))


def league(n=300, seed=26):
    rng = random.Random(seed)
    top = sorted((p for p, (m, g) in SS.items() if g >= 40 and POS.get(p)), key=lambda p: -SS[p][0])
    rows = {a: {k: [] for k in ('real', 'wins')} for a in ARMS}
    gap, lane_e = [], []
    for _ in range(n):
        w = rng.randint(1, 25)
        pool = [p for p in top if w in W[p]][:140]
        bands = [rng.sample(pool[k * 10:(k + 1) * 10], 10) for k in range(14)]
        res = [team_week([bands[k][t] for k in range(14)], w) for t in range(10)]
        base = [r['lane'][0] for r in res]
        lane_e.append(base)
        gap.append([r['hindsight'][0] - r['lane'][0] for r in res])
        for a in ARMS:
            rows[a]['real'].append([r[a][0] - r['lane'][0] for r in res])
            rows[a]['wins'].append([20 * (wins(base[:i] + [res[i][a][0]] + base[i + 1:], i) - wins(base, i)) for i in range(10)])
    b = random.Random(7)
    print(f"Random leagues: {n} league-weeks x 10 teams; lane {boot(lane_e, b)[0]:.1f} FP/team-week, "
          f"hindsight gap {boot(gap, b)[0]:.1f}")
    for a in ARMS:
        out = []
        for k, unit in (('real', 'FP/wk'), ('wins', 'wins/20 wk')):
            mean, lo, hi = boot(rows[a][k], b)
            out.append(f'{mean:+.2f} {unit} [{lo:+.2f}, {hi:+.2f}]')
        print(f'  {a} vs lane: ' + '; '.join(out))


if __name__ == '__main__':
    import datetime
    d1, d2 = datetime.date(2025, 11, 3), datetime.date(2025, 11, 4)
    g = {'s': {d2: 0.92}, 'b': {d1: 0.92}, 'a': {d2: 0.92}}
    f = {'s': 60.0, 'b': 30.0, 'a': 40.0}
    POS.update(s=['C'], b=['C'], a=['PG'])
    act = {('s', d2): 50.0, ('b', d1): 45.0, ('a', d2): 20.0}
    rs = {6: [(d1, 'b'), (d2, 's')], 0: [(d2, 'a')]}  # b feeds C Mon; s (C) returns Tue; a (PG) plays Tue
    base = {6: 's', 0: 'a'}
    assert replay(base, rs, [d1, d2], g, f, act, False) == (70.0, 0)  # 45 < s's line, so s's 50 and a's 20 count
    # Pooled: b's 45 can't close PG (s is C-only), so the result is the same.
    assert replay(base, rs, [d1, d2], g, f, act, True) == (70.0, 0)
    # j (C, 80/g) owns UTIL and returns Tue; c (C, 40/g) owns C. b's 45 Mon in UTIL closes C via one hop (j moves to C).
    g.update(j={d2: 0.92}, c={d2: 0.92})
    f.update(j=80.0, c=40.0)
    POS.update(j=['C'], c=['C'])
    act.update({('j', d2): 70.0, ('c', d2): 30.0})
    rs, base = {7: [(d1, 'b'), (d2, 'j')], 6: [(d2, 'c')]}, {7: 'j', 6: 'c'}
    assert replay(base, rs, [d1, d2], g, f, act, False) == (100.0, 0)  # 45 < 73.6: wait; j 70 + c 30
    assert replay(base, rs, [d1, d2], g, f, act, True) == (115.0, 1)  # lock 45 via C (36.8 + 1), j's 70 stands
    args = [int(x) for x in sys.argv[1:]]
    ours()
    league(*args)
