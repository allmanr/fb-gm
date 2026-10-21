"""Issue #22 check: is the realized-over-expected gain in q22 a code effect or the real scores?
Same plans as q22 (gap 3 h); scores replayed three ways: the model expectation, 20 model-world weeks (draws from
gm.draws at gm.play_on odds), and the real 2025-26 box scores. Usage: python3 q22_check.py"""
import random
from q22 import *
rng = random.Random(22); sim = random.Random(3)
top = sorted((p for p, (m, g) in SS.items() if g >= 40 and POS.get(p)), key=lambda p: -SS[p][0])
e = x = s = n = 0.0
for _ in range(60):
    w = rng.randint(1, 25)
    pool = [p for p in top if w in W[p]][:140]
    bands = [rng.sample(pool[k * 10:(k + 1) * 10], 10) for k in range(14)]
    for t in range(10):
        arms, games, fpg, actual = plans([bands[k][t] for k in range(14)], w)
        for _ in range(20):  # model-world scores: same plans, draws from the model itself
            fake = {(p, d): (sim.choice(gm.draws(fpg[p])) if sim.random() < games[p][d] else None) for (p, d) in actual}
            s += sum(realized(r, games, fpg, fake) - realized(b, games, fpg, fake) for b, r in zip(arms['base'].values(), arms[3.0].values())) / 20
        e += sum(value(r, games, fpg) - value(b, games, fpg) for b, r in zip(arms['base'].values(), arms[3.0].values()))
        x += sum(realized(r, games, fpg, actual) - realized(b, games, fpg, actual) for b, r in zip(arms['base'].values(), arms[3.0].values()))
        n += 1
print(f'per team-week: expected {e/n:+.2f}  model-world realized {s/n:+.2f}  real-scores realized {x/n:+.2f}')
