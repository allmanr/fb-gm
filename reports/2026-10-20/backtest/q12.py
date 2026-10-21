"""Q1 (single-slot policy backtest), Q2 (calibration + DNP), Q4 (threshold table)."""
from collections import defaultdict
from lib import load, season_stats, seq_value, r1, rb

D = load()
W, SS = D['weeks'], season_stats(D['weeks'])
PLAYERS = [p for p, (m, g) in SS.items() if g >= 40]


def causal_ppg(p):
    """Per-week FP/g known before the week: 2024-25 mean (weight <=10 g) else 30 FP/g (weight 5)."""
    pm, pn = D['prior'].get(p, (30.0, 0))
    w0 = min(pn, 10) if pn >= 10 else 5
    pm = pm if pn >= 10 else 30.0
    tot, n, out = pm * w0, w0, {}
    for w in sorted(W[p]):
        out[w] = tot / n
        for _, s in W[p][w]:
            if s is not None:
                tot, n = tot + s, n + 1
    return out


def thresholds(ppg, k_max, q=0.0, m=1.0):
    return [m * seq_value((r1(ppg),) * k, q) for k in range(k_max + 1)]


def run(games, th):
    """Threshold policy on a schedule [(date, fp|None)]; th[k] = wait value with k games left."""
    n = len(games)
    for j, (_, s) in enumerate(games):
        left = n - 1 - j
        if left == 0:
            return s or 0.0
        if s is not None and s >= th[left]:
            return s
    return 0.0


def main():
    res = defaultdict(lambda: defaultdict(float))  # variant -> metric -> sum
    cnt = defaultdict(int)
    calib = defaultdict(lambda: [0, 0.0, 0.0, 0.0])  # (bucket, k) -> n, pred, pred_q, real
    haz = defaultdict(lambda: [0, 0])  # key -> [opportunities, dnps]
    mults = [0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 1.0, 1.05]
    for p in PLAYERS:
        oracle = SS[p][0]
        cz = causal_ppg(p)
        for w, games in W[p].items():
            played = [s for _, s in games if s is not None]
            # DNP hazard: next scheduled game in-week, given he played the previous one
            for (d0, a), (d1, b) in zip(games, games[1:]):
                if a is not None:
                    b2b = (int(d1[-2:]) - int(d0[-2:])) == 1 or d1[5:7] != d0[5:7] and d1[-2:] == '01'
                    keys = ['all', 'b2b' if b2b else 'rest>=1d', f'fp{min(int(oracle // 10) * 10, 60)}']
                    if oracle >= 25:
                        keys += ['reg25', 'reg25_' + ('b2b' if b2b else 'rest')]
                        if SS[p][1] >= 65:
                            keys.append('reg25_65g')
                    for key in keys:
                        haz[key][0] += 1
                        haz[key][1] += b is None
            if not played:
                cnt['dead_weeks'] += 1
                continue
            n = len(games)
            cnt[n] += 1
            cnt['weeks'] += 1
            r = res['n']
            r['last'] += games[-1][1] or 0.0
            r['first'] += played[0]
            r['max'] += max(played)
            r['mean_game'] += sum(played) / len(played)
            for label, ppg in (('oracle', oracle), ('causal', cz[w])):
                r[label] += run(games, thresholds(ppg, n))
                r[label + '_pred'] += rb.lock_values(r1(ppg), n)[n]
            for q in (0.03, 0.05, 0.08, 0.12):
                r[f'oracle_q{q}'] += run(games, thresholds(oracle, n, q))
                r[f'causal_q{q}'] += run(games, thresholds(cz[w], n, q))
            for m in mults:
                r[f'oracle_m{m}'] += run(games, thresholds(oracle, n, 0, m))
                r[f'causal_m{m}'] += run(games, thresholds(cz[w], n, 0, m))
            # continuation calibration: at each played game with k left, value of waiting
            for j, (_, s) in enumerate(games[:-1]):
                if s is None:
                    continue
                k = n - 1 - j
                b = min(int(oracle // 10) * 10, 60)
                clean = all(x is not None for _, x in games[j + 1:])
                keys = [(b, k), ('all', k)] + ([('clean', k)] if clean else [])
                if oracle >= 25:
                    keys += [('reg25', k)] + ([('reg25clean', k)] if clean else [])
                for key in keys:
                    c = calib[key]
                    c[0] += 1
                    c[1] += rb.lock_values(r1(oracle), k)[k]
                    c[2] += seq_value((r1(oracle),) * k, 0.05)
                    c[3] += run(games[j + 1:], thresholds(oracle, k))
            # same for calibration of whole-week E[locked] by bucket/n
            b = min(int(oracle // 10) * 10, 60)
            c = calib[('week', b, n)]
            c[0] += 1
            c[1] += rb.lock_values(r1(oracle), n)[n]
            c[2] += seq_value((r1(oracle),) * n, 0.05)
            c[3] += run(games, thresholds(oracle, n))

    N = cnt['weeks']
    r = {k: v / N for k, v in res['n'].items()}
    print(f'players={len(PLAYERS)} active player-weeks={N} dead weeks(0 games played)={cnt["dead_weeks"]}')
    print('games/week dist', {k: cnt[k] for k in range(1, 6)})
    for k in ('last', 'first', 'max', 'mean_game', 'oracle', 'oracle_pred', 'causal', 'causal_pred'):
        print(f'  {k:12s} {r[k]:6.2f}')
    gap = r['max'] - r['last']
    for k in ('oracle', 'causal') + tuple(f'{a}_q{q}' for a in ('oracle', 'causal') for q in (0.03, 0.05, 0.08, 0.12)):
        print(f'  {k:16s} {r[k]:6.2f}  +{r[k]-r["last"]:.2f} vs last, +{r[k]-r["first"]:.2f} vs first, '
              f'capture {(r[k]-r["last"])/gap:.1%} of last->max gap, {(r[k]-r["first"])/(r["max"]-r["first"]):.1%} of first->max')
    print('  multiplier sweep (oracle / causal):')
    for m in mults:
        print(f'    m={m:.2f}  {r[f"oracle_m{m}"]:.3f}  {r[f"causal_m{m}"]:.3f}')
    print('\nDNP hazard (next in-week game, given played previous):')
    for k, (o, d) in sorted(haz.items(), key=str):
        print(f'  {k:10s} n={o:6d} p_dnp={d/o:.3f}')
    print('\nContinuation calibration: (FP bucket, games left) n pred pred_q.05 realized real/pred')
    for key in sorted((k for k in calib if k[0] != 'week'), key=str):
        n, a, b, c = calib[key]
        if n >= 30:
            print(f'  {str(key):12s} n={n:5d} pred={a/n:6.2f} pred_q={b/n:6.2f} real={c/n:6.2f} ratio={c/a:.3f}')
    print('\nWhole-week E[locked]: (bucket, n games) pred pred_q.05 realized')
    for key in sorted((k for k in calib if k[0] == 'week'), key=str):
        n, a, b, c = calib[key]
        if n >= 30:
            print(f'  {str(key[1:]):10s} n={n:5d} pred={a/n:6.2f} pred_q={b/n:6.2f} real={c/n:6.2f} ratio={c/a:.3f}')
    print('\nQ4 thresholds as multiple of FP/g (lock if score >= x * FP/g): q=0 / q=0.08 / q=0.12(b2b)')
    for ppg in (30, 40, 50, 60, 75):
        print(f'  {ppg} FP/g: ' + '  '.join(
            f'k{k}: ' + '/'.join(f'{seq_value((float(ppg),) * k, q) / ppg:.2f}' for q in (0, 0.08, 0.12))
            for k in range(1, 5)))
    print('  waiting-value multiplier V_k(q=.08)/V_k(0) at 45 FP/g:',
          [round(seq_value((45.0,) * k, 0.08) / seq_value((45.0,) * k), 3) for k in range(1, 5)])
    print('  approx V_k(q) ~ V_k(0) - q*ppg check at 45:',
          [round((seq_value((45.0,) * k) - 0.08 * 45) / seq_value((45.0,) * k, 0.08), 3) for k in range(1, 5)])

if __name__ == '__main__':
    assert run([('a', 10.0), ('b', None)], [0, 5]) == 10.0
    assert run([('a', 3.0), ('b', None)], [0, 5]) == 0.0
    assert run([('a', None), ('b', 7.0)], [0, 5]) == 7.0
    main()
