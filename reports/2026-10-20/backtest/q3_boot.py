"""Q3 bootstrap: 95% CIs for the pooled bench discount factors (sum N / sum D over random rosters).

Reads q3_<scenario>.json written by `python3 q3.py 300`; resamples rosters with replacement.
Usage: python3 q3_boot.py > q3_boot.out
"""
import json, random

B = 2000


def pooled(rows):
    return sum(n for n, _ in rows) / sum(d for _, d in rows)


random.seed(7)
for scen in ('surprise', 'realistic', 'known'):
    agg = json.load(open(f'q3_{scen}.json'))
    parts = []
    for t in ('all5', 'top3', 'V3', 'V5'):
        rows = list(zip(agg['N_' + t], agg['D_' + t]))
        boots = sorted(pooled([random.choice(rows) for _ in rows]) for _ in range(B))
        parts.append(f'{t} {pooled(rows):.3f} [{boots[int(0.025 * B)]:.3f},{boots[int(0.975 * B)]:.3f}]')
    print(f'{scen} {len(agg["gain"])} ' + ' | '.join(parts))
