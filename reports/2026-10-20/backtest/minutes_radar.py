"""Minutes-trend radar backtest (issue #11 part 2): after a player's last-3-game minutes exceed his season-to-date
average by T+, does he beat the in-season blend's FP/g over the next two weeks?

Logs: rebuild_board.season_weeks (Sleeper weekly stats, cached in the repo's .cache/). Season 2025 = 2025-26, 2024 =
2024-25 as an out-of-sample check. Prediction = rebuild_board.blend: prior = the player's previous-season FP/g (>= 10 GP,
k = BLEND_K), else NO_PRIOR_PPG at NO_PRIOR_K, as season_actuals does for off-board players; n = games played so far.
Event: after his game on date d with n >= 6 games played, last-3 minutes/g - season-to-date minutes/g >= T (season
average includes the last 3, as a box-score line shows it). One event per player per 14 days (first trigger) so a
streak counts once. Target: FP/g over his games in (d, d + 14], >= 3 games. Population: blend prediction <= 35 FP/g
(waiver-wire range; the board's replacement level is ~27). Alternative predictor (what gm.py fa prints): last-3
minutes/g x season-to-date FP/minute; shrinking FP/minute toward the blend's rate by the same k changed RMSE < 0.1.

Usage: python3 minutes_radar.py > minutes_radar.out   (downloads 2023 and 2024 logs into .cache on first use)
"""
import datetime, math, os, random, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import rebuild_board as rb  # noqa: E402

THRESHOLDS = (4, 6, 8, 10, 12)
MIN_N, WINDOW, MIN_TARGET_GAMES, MAX_PRED = 6, 14, 3, 35.0


def logs(season):
    return rb.game_logs(rb.season_weeks(season))


def events(season):
    """[(T-free event dict)] for every player-game with n >= MIN_N: minutes jump, blend prediction, alternative, target."""
    cur = logs(season)
    prior = {p: sum(g[2] for g in gs) / len(gs) for p, gs in logs(season - 1).items() if len(gs) >= 10}
    out = []
    for pid, games in cur.items():
        days = [datetime.date.fromisoformat(g[0]) for g in games]
        for i in range(MIN_N - 1, len(games)):
            n, head = i + 1, games[:i + 1]
            fp, mins = sum(g[2] for g in head), sum(g[3] for g in head)
            p, k = (prior[pid], rb.BLEND_K) if pid in prior else (rb.NO_PRIOR_PPG, rb.NO_PRIOR_K)
            pred = rb.blend(p, dict(games=n, actual_ppg=fp / n, prior_k=k))
            nxt = [g[2] for g, day in zip(games[i + 1:], days[i + 1:]) if day <= days[i] + datetime.timedelta(WINDOW)]
            if len(nxt) < MIN_TARGET_GAMES or pred > MAX_PRED or mins <= 0:
                continue
            last3 = sum(g[3] for g in head[-3:]) / 3
            out.append(dict(pid=pid, day=days[i], jump=last3 - mins / n, pred=pred, alt=last3 * fp / mins,
                            target=sum(nxt) / len(nxt)))
    return out


def declustered(evs, flagged):
    """First qualifying event per player per WINDOW days."""
    keep, last = [], {}
    for e in sorted(evs, key=lambda e: (e['pid'], e['day'])):
        if flagged(e) and (e['pid'] not in last or e['day'] > last[e['pid']] + datetime.timedelta(WINDOW)):
            keep.append(e)
            last[e['pid']] = e['day']
    return keep


def summary(rows, seed=11):
    """n, players, mean residual (target - blend) with a player-cluster bootstrap 95% CI, RMSE blend vs alternative,
    and the alternative's mean error (alt - target)."""
    res = [e['target'] - e['pred'] for e in rows]
    by_player = {}
    for e in rows:
        by_player.setdefault(e['pid'], []).append(e['target'] - e['pred'])
    groups, rng, boots = list(by_player.values()), random.Random(seed), []
    for _ in range(1000):
        pick = [x for g in (rng.choice(groups) for _ in groups) for x in g]
        boots.append(sum(pick) / len(pick))
    boots.sort()
    rmse = lambda key: math.sqrt(sum((e['target'] - e[key]) ** 2 for e in rows) / len(rows))  # noqa: E731
    return (f"n {len(rows):5d} players {len(groups):4d} | resid {sum(res) / len(res):+5.2f} "
            f"[{boots[25]:+5.2f},{boots[974]:+5.2f}] | RMSE blend {rmse('pred'):5.2f} alt {rmse('alt'):5.2f} "
            f"(alt bias {sum(e['alt'] - e['target'] for e in rows) / len(rows):+5.2f})")


if __name__ == '__main__':
    for season in (2025, 2024):
        evs = events(season)
        print(f"Season {season}-{(season + 1) % 100:02d} (prior {season - 1}-{season % 100:02d}); "
              f"player-games with n >= {MIN_N}, blend <= {MAX_PRED:g}, >= {MIN_TARGET_GAMES} games in next {WINDOW} days")
        print(f"  baseline (all, 1 per player per {WINDOW}d): {summary(declustered(evs, lambda e: True))}")
        for t in THRESHOLDS:
            print(f"  last-3 min - season avg >= {t:2d}:      {summary(declustered(evs, lambda e, t=t: e['jump'] >= t))}")
        print(f"  jump in [4, 8):                  {summary(declustered(evs, lambda e: 4 <= e['jump'] < 8))}")
