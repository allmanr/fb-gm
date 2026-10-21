"""Issue #32: do per-game context means (opponent, teammates out) make better lock calls? 2025-26 logs.

Context model, fit on 2024-25 and applied to 2025-26 (no in-season tuning):
  residual = score - player's running FP/g (prior season mean, weight <= 10 games, else 30 FP/g at weight 5)
           ~ a * opp + b * vac * share
  opp   = the opponent's running mean residual allowed before this date, shrunk: sum / (n + OPP_K)
  vac   = running FP/g of teammates (25+ FP/g, 5+ games) with a DNP row in this game
  share = his running FP/g / his and his playing teammates' running FP/g
OPTIMISTIC on purpose: a teammate's DNP counts as known at every earlier lock decision that week. If this arm
misses the gate (0.3 wins per 20-week season), a realistic one (absences known only near tip) misses it too.

Arms (q26's replay, same plan and base lineup, pooled bench locks as `gm.py lock` does):
  pooled - lock lines from the player's weekly FP/g (today's policy)
  ctx    - lock lines from per-game means fpg + a*opp + b*vac*share (0.5 FP grid)
Random 10-team leagues (q26's sampler); wins switch one team to ctx, others on pooled.
ponytail: context feeds lock lines only, not the base lineup or rotation; add those only if this clears the gate.
Usage: python3 q32.py [league_weeks=300] [seed=32]
"""
import datetime, random, sys
from collections import defaultdict
from lib import _load_season, r1
from q22 import W, POS, SS, boot, wins
from q26 import plans, replay
import gm

OPP_K, VAC_MIN, MIN_G = 150, 25.0, 5


def features(folder, prior):
    """-> {(pid, date): (residual or None, opp, vac*share, running FP/g)} over one season, causal by date."""
    rows = _load_season(folder)
    by_game = defaultdict(list)
    for w, d, t, g, p, s in rows:
        by_game[(d, g)].append((t, p, s))
    run = {}  # pid -> [total, n]
    allowed = defaultdict(lambda: [0.0, 0])  # team -> [sum residual allowed, n]
    out = {}
    for d in sorted({d for d, _ in by_game}):  # a date's games update the running means only after the date
        updates, opp_updates = [], []
        for (dd, g), ps in by_game.items():
            if dd != d:
                continue
            teams = sorted({t for t, _, _ in ps})
            if len(teams) != 2:
                continue

            def ppg(p):
                pm, pn = prior.get(p, (30.0, 0))
                w0, pm = (min(pn, 10), pm) if pn >= 10 else (5, 30.0)
                tot, n = run.get(p, [0.0, 0])
                return (pm * w0 + tot) / (w0 + n), n
            for t in teams:
                opp = teams[1] if t == teams[0] else teams[0]
                a = allowed[opp]
                of = a[0] / (a[1] + OPP_K)
                mine = [(p, s) for tt, p, s in ps if tt == t]
                gone = {p: ppg(p)[0] for p, s in mine if s is None and ppg(p)[0] >= VAC_MIN and ppg(p)[1] >= MIN_G}
                act = sum(ppg(p)[0] for p, s in mine if s is not None)
                for p, s in mine:
                    m, n = ppg(p)
                    res = s - m if s is not None else None
                    vac = sum(gone.values()) - gone.get(p, 0.0)  # teammates only: his own DNP is not context
                    out[(p, d)] = (res if n >= MIN_G else None, of, vac * m / (act + m * (s is None)) if act else 0.0, m)
                    if s is not None:
                        updates.append((p, s))
                        if n >= MIN_G and m >= 20:
                            opp_updates.append((opp, s - m))
        for p, s in updates:
            r = run.setdefault(p, [0.0, 0])
            r[0] += s
            r[1] += 1
        for t, r in opp_updates:
            allowed[t][0] += r
            allowed[t][1] += 1
    return out


def fit(feat, min_ppg=25.0):
    """OLS on centered features: residual - mean ~ a * (opp - mean) + b * (vac_share - mean), players at
    min_ppg+ running FP/g -> (a, b, R2, n, (mean opp, mean vac_share)). Centering keeps the average shift 0:
    an all-positive teammates term would otherwise raise every later game and bias lock lines toward waiting."""
    rows = [(r, o, v) for r, o, v, m in feat.values() if r is not None and m >= min_ppg]
    mr, mo, mv = (sum(x[i] for x in rows) / len(rows) for i in range(3))
    X = [(o - mo, v - mv) for r, o, v in rows]
    Y = [r - mr for r, o, v in rows]
    sxx = [[sum(x[i] * x[j] for x in X) for j in range(2)] for i in range(2)]
    sxy = [sum(x[i] * y for x, y in zip(X, Y)) for i in range(2)]
    det = sxx[0][0] * sxx[1][1] - sxx[0][1] ** 2
    a = (sxy[0] * sxx[1][1] - sxy[1] * sxx[0][1]) / det
    b = (sxy[1] * sxx[0][0] - sxy[0] * sxx[0][1]) / det
    sse = sum((y - a * o - b * v) ** 2 for (o, v), y in zip(X, Y))
    return a, b, 1 - sse / sum(y * y for y in Y), len(Y), (mo, mv)


def prior_means(folder):
    tot = defaultdict(lambda: [0.0, 0])
    for w, d, t, g, p, s in _load_season(folder):
        if s is not None:
            tot[p][0] += s
            tot[p][1] += 1
    return {p: (a / n, n) for p, (a, n) in tot.items()}


F24 = features('data24', {})
A, B, R2, N, MU = fit(F24)
F25 = features('data', prior_means('data24'))
print(f'context fit on 2024-25 ({N} player-games at 25+ FP/g): a={A:.3f} per FP of opponent residual, '
      f'b={B:.3f} per vacated FP x share; R2 {R2:.3f}', flush=True)
a25, b25, r2_25, _, _ = fit(F25)
print(f'same fit on 2025-26 for reference (not used): a={a25:.3f}, b={b25:.3f}, R2 {r2_25:.3f}', flush=True)


def shift(p, day):
    f = F25.get((p, day.isoformat()))
    return A * (f[1] - MU[0]) + B * (f[2] - MU[1]) if f else 0.0


def team_week(roster, w):
    base, lane, seated, days, games, fpg, actual = plans(roster, w)
    mean = lambda p, d: max(1.0, r1(fpg[p] + shift(p, d)))
    return {'pooled': replay(base, seated, days, games, fpg, actual, True)[0],
            'ctx': replay(base, seated, days, games, fpg, actual, True, mean)[0]}


def league(n=300, seed=32):
    rng = random.Random(seed)
    top = sorted((p for p, (m, g) in SS.items() if g >= 40 and POS.get(p)), key=lambda p: -SS[p][0])
    real, won, shifts = [], [], []
    for _ in range(n):
        w = rng.randint(1, 25)
        pool = [p for p in top if w in W[p]][:140]
        bands = [rng.sample(pool[k * 10:(k + 1) * 10], 10) for k in range(14)]
        res = [team_week([bands[k][t] for k in range(14)], w) for t in range(10)]
        base = [r['pooled'] for r in res]
        real.append([r['ctx'] - r['pooled'] for r in res])
        won.append([20 * (wins(base[:i] + [res[i]['ctx']] + base[i + 1:], i) - wins(base, i)) for i in range(10)])
    b = random.Random(7)
    print(f'Random leagues: {n} league-weeks x 10 teams')
    for k, rows, unit in (('real', real, 'FP/wk'), ('wins', won, 'wins/20 wk')):
        mean, lo, hi = boot(rows, b)
        print(f'  ctx vs pooled: {mean:+.2f} {unit} [{lo:+.2f}, {hi:+.2f}]')


if __name__ == '__main__':
    keep = [(p, d, f) for (p, d), f in F25.items() if f[0] is not None and f[3] >= 25]
    sh = [shift(p, datetime.date.fromisoformat(d)) for p, d, f in keep]
    res = [f[0] - sum(x[2][0] for x in keep) / len(keep) for x in keep for f in [x[2]]]
    r2 = 1 - sum((r - s) ** 2 for r, s in zip(res, sh)) / sum(r * r for r in res)
    print(f'2025-26 per-game shift at 25+ FP/g (out of sample): mean {sum(sh) / len(sh):+.2f}, mean |shift| '
          f'{sum(map(abs, sh)) / len(sh):.2f} FP, {100 * sum(abs(x) >= 4 for x in sh) / len(sh):.1f}% of games >= 4 FP; '
          f'R2 vs centered residual {r2:.3f}', flush=True)
    # Leak guard: his own DNP must not raise his own shift (it did before the teammates-only fix: -3.15 FP/wk).
    dnp = [shift(p, datetime.date.fromisoformat(d)) for (p, d), f in F25.items() if f[0] is None and f[3] >= 25]
    assert abs(sum(dnp) / len(dnp) - sum(sh) / len(sh)) < 1.0, (sum(dnp) / len(dnp), sum(sh) / len(sh))
    league(*[int(x) for x in sys.argv[1:]])
