"""Q3: value of bench rotation and of roster spots 10-14, 2025-26 game logs replayed week by week.

Policy simplifications (see REPORT.md): oracle season FP/g known; same-date games can't share a slot
(no tip-time data); a never-locked slot scores its last roll (0 if that roll was a DNP).
Scenarios: 'surprise' = every DNP revealed at tip (roll is 0); 'realistic' = whole-week outs known,
in-week DNPs revealed at tip; 'known' = perfect availability foresight.
"""
import json, random, sys
from collections import defaultdict
from lib import load, player_snapshot, season_stats, seq_value, r1

D = load()
W, SS = D['weeks'], season_stats(D['weeks'])
CACHE = player_snapshot()
SLOTS = [('PG', {'PG'}), ('SG', {'SG'}), ('G', {'PG', 'SG'}), ('SF', {'SF'}), ('PF', {'PF'}),
         ('F', {'SF', 'PF'}), ('C', {'C'}), ('UTIL', None), ('UTIL2', None)]
POS = {p: set(CACHE.get(p, {}).get('fantasy_positions') or []) for p in SS}
PPG = {p: r1(m) for p, (m, g) in SS.items()}


def ok(p, slot):
    el = SLOTS[slot][1]
    return bool(POS[p]) and (el is None or bool(POS[p] & el))


def match(players, slots):
    """Greedy max-weight transversal matching: players in priority order -> {slot: player}."""
    own = {}

    def aug(p, seen):
        for s in slots:
            if s not in seen and ok(p, s):
                seen.add(s)
                if s not in own or aug(own[s], seen):
                    own[s] = p
                    return True
        return False

    for p in players:
        aug(p, set())
    return own


def sched(p, w, scen):
    g = W[p].get(w, [])
    if scen == 'known':
        return [(d, s) for d, s in g if s is not None]
    if scen == 'realistic' and all(s is None for _, s in g):
        return []  # whole-week absences (long injuries) are known; in-week DNPs are surprises
    return g


def week_val(p, n):
    return seq_value((PPG[p],) * n) if n else 0.0


def starters(roster, w, scen):
    order = sorted(roster, key=lambda p: -week_val(p, len(sched(p, w, scen))))
    return match(order, range(9))


def fixed_week(roster, w, scen):
    """No rotation: best 9 by weekly expected value, each locks alone with single-player thresholds."""
    tot = 0.0
    for s, p in starters(roster, w, scen).items():
        g = sched(p, w, scen)
        for j, (_, x) in enumerate(g):
            k = len(g) - 1 - j
            if k == 0:
                tot += x or 0.0
            elif x is not None and x >= seq_value((PPG[p],) * k):
                tot += x
                break
    return tot


def rotate_week(roster, w, scen):
    """Home slots = the fixed policy's best 9. Each day an open slot's home player rolls if he plays;
    otherwise the best free non-home player who plays that day fills it (extra roll). After games a
    slot locks if x >= optimal-stopping value of its planned future rolls (largest surplus first,
    replanning after each lock). A filler locked into a slot frees that slot's home player to fill."""
    games = {p: dict(sched(p, w, scen)) for p in roster}
    days = sorted({d for g in games.values() for d in g})
    home = starters(roster, w, scen)
    by_ppg = sorted(roster, key=lambda p: -PPG[p])
    free = set(roster)

    def assign(d):
        out = {s: p for s, p in home.items() if p in free and d in games[p]}
        idle = [s for s in home if s not in out]
        homes = set(home.values())
        out.update(match([p for p in by_ppg if p in free and p not in homes and d in games[p]], idle))
        return out

    def future(i):
        rolls = defaultdict(list)
        for d in days[i:]:
            for s, p in assign(d).items():
                rolls[s].append(PPG[p])
        return rolls

    last, tot = {}, 0.0
    for i, d in enumerate(days):
        today = assign(d)
        for s, p in today.items():
            last[s] = games[p][d] or 0.0
        while True:
            fut, best = future(i + 1), None
            for s, p in today.items():
                x = games[p][d]
                if s in home and x is not None:
                    gain = x - (seq_value(tuple(fut[s])) if fut[s] else 0.0)
                    if gain >= 0 and (best is None or gain > best[0]):
                        best = (gain, s, p, x)
            if not best:
                break
            _, s, p, x = best
            tot += x
            free.discard(p)
            del home[s]  # slot closed; if a filler locked, the old home player is now a free filler
    return tot + sum(last.get(s, 0.0) for s in home)


def season(roster, fn, scen):
    return sum(fn(roster, w, scen) for w in range(1, 26)) / 25


def standalone(p, scen):
    """Weekly locked value as a lone starter (threshold policy), 0 in weeks without games."""
    return season([p], fixed_week, scen)


def pid(name):
    return next(p for p, v in CACHE.items() if (v.get('full_name') or '') == name and p in SS)


OURS = ['Devin Booker', 'RJ Barrett', "De'Aaron Fox", 'Deni Avdija', 'LeBron James', 'Pascal Siakam',
        'Nikola Jokić', 'James Harden', 'Jarrett Allen', 'VJ Edgecombe', 'CJ McCollum', 'Jakob Poeltl',
        'P.J. Washington']


def main(n_random):
    random.seed(7)
    ours = [pid(n) for n in OURS]
    # Darius Acuff (2026 rookie, no 2025-26 logs; board 36.4 FP/g PG/SG) -> closest PG/SG with 60+ games
    sub = min((p for p, (m, g) in SS.items() if g >= 60 and POS[p] & {'PG', 'SG'} and p not in ours),
              key=lambda p: abs(SS[p][0] - 36.4))
    ours.append(sub)
    print('Acuff substitute:', D['names'][sub], round(SS[sub][0], 1), SS[sub][1], sorted(POS[sub]))
    total_fp = sorted((p for p in SS if POS[p]), key=lambda p: -SS[p][0] * SS[p][1])
    pool, reps = total_fp[:140], total_fp[140:180]
    print(f'pool 1-140 by season total FP: FP/g range {SS[pool[-1]][0]:.1f}-{SS[pool[0]][0]:.1f}; '
          f'replacement 141-180 mean FP/g {sum(SS[p][0] for p in reps)/len(reps):.1f}')
    rosters = [('ours', ours)]
    while len(rosters) < n_random + 1:
        r = [random.choice(pool[i * 10:(i + 1) * 10]) for i in range(14)]
        if len(match(r, range(9))) == 9:
            rosters.append((f'rand{len(rosters)}', r))
    for scen in ('surprise', 'realistic', 'known'):
        agg = defaultdict(list)
        for tag, r in rosters:
            r = sorted(r, key=lambda p: -SS[p][0] * SS[p][1])  # roster order: season total FP
            sa = {p: standalone(p, scen) for p in r}
            fixed14 = season(r, fixed_week, scen)
            rot = {k: season(r[:k], rotate_week, scen) for k in range(9, 15)}
            fixed9 = season(r[:9], fixed_week, scen)
            rp = random.sample(reps, 5)
            sa_rp = [standalone(p, scen) for p in rp]
            row = dict(fixed14=fixed14, fixed9=fixed9, rot14=rot[14], gain=rot[14] - fixed14,
                       bench_sa=sum(sa[p] for p in r[9:]))
            for k in range(10, 15):
                row[f'm{k}'] = rot[k] - rot[k - 1]
            # discount vs an empty spot: team gain / standalone weekly lock value
            row['N_all5'], row['D_all5'] = rot[14] - rot[9], row['bench_sa']
            row['N_top3'], row['D_top3'] = rot[12] - rot[9], sum(sa[p] for p in r[9:12])
            # discount on surplus V: bench vs replacement-level fillers (what trade.py's bench V measures)
            row['N_V3'] = rot[12] - season(r[:9] + rp[:3], rotate_week, scen)
            row['D_V3'] = sum(sa[p] for p in r[9:12]) - sum(sa_rp[:3])
            row['N_V5'] = rot[14] - season(r[:9] + rp, rotate_week, scen)
            row['D_V5'] = row['bench_sa'] - sum(sa_rp)
            row['rep_sa'] = sum(sa_rp) / 5
            for t in ('all5', 'top3', 'V3', 'V5'):
                row['d_' + t] = row['N_' + t] / row['D_' + t] if row['D_' + t] > 5 else None
            if tag == 'ours':
                print(f'\n[{scen}] OUR ROSTER  fixed-9 (best 9 weekly) {fixed14:.1f}  rotation-14 {rot[14]:.1f}  '
                      f'gain {rot[14]-fixed14:+.1f} FP/wk; rotation with top k: ' +
                      ' '.join(f'{k}:{v:.1f}' for k, v in rot.items()))
                for k in range(10, 15):
                    p = r[k - 1]
                    print(f'   spot {k} {D["names"][p]:18s} {SS[p][0]:.1f}/g standalone {sa[p]:.1f}/wk '
                          f'marginal {row[f"m{k}"]:+.1f}')
                for t in ('all5', 'top3', 'V3', 'V5'):
                    print(f'   {t}: team gain {row["N_"+t]:+.1f}/wk / standalone {row["D_"+t]:.1f} = {row["d_"+t]}')
            else:
                for k, v in row.items():
                    if v is not None:
                        agg[k].append(v)
        json.dump(agg, open(f'q3_{scen}.json', 'w'))
        print(f'[{scen}] RANDOM ROSTERS n={len(agg["gain"])} (mean, p10, p90):')
        for k, v in agg.items():
            v = sorted(v)
            if k.startswith('N_'):
                t = k[2:]
                print(f'   pooled d_{t} = sum N / sum D = {sum(v)/sum(agg["D_"+t]):.3f}')
                continue
            if k.startswith('D_'):
                continue
            print(f'   {k:11s} {sum(v)/len(v):7.2f}  {v[len(v)//10]:7.2f}  {v[9*len(v)//10]:7.2f}')
        sys.stdout.flush()


if __name__ == '__main__':
    # self-check: a lone player with rotation equals the fixed single-slot policy
    p = pid('Nikola Jokić')
    assert abs(season([p], rotate_week, 'surprise') - season([p], fixed_week, 'surprise')) < 1e-9
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
