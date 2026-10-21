# Late-season shutdowns in the playoff weeks (issue #6, private #31)

**Verdict: built.** In fantasy-playoff weeks, fantasy-relevant players on the 10 worst NBA teams keep only **0.71** of their usual available weeks (95% CI 0.57–0.84). Players on other teams keep **0.92** (0.86–0.98). `trade.py`'s playoff weighting now applies this factor. Before, it modeled only schedules, whose spread across teams is about ±3%.

## Method

[`q31.py`](../2026-10-20/backtest/q31.py) uses Sleeper's 2024-25 and 2025-26 game logs and schedules ([output](../2026-10-20/backtest/q31.out)).

- **Players:** 35+ FP/g over 25+ games from Nov 1 to Feb 14 in our scoring: 75 players in 2024-25 and 80 in 2025-26.
- **Groups:** the bottom 10 by win percentage at Feb 15 (the NBA trade deadline), from schedule results. Using deadline standings avoids hindsight.
- **Unit:** a player-week in which his team plays at least one game. The week is *out* if he played none of them. Lock-In can't recover a whole lost week, so V, the surplus over a replacement, is lost with it. A missed game inside a week mostly costs one lock roll, so it's reported but not modeled.
- **Factor:** (1 − out rate in the playoff-window weeks) ÷ (1 − out rate Nov–Feb). Injuries that the board's GP already prices cancel out. The playoff window is the weeks starting Mar 8–24, Sleeper weeks 21–23 in both seasons, the same weeks as our playoffs.
- **CI:** a 2,000-draw bootstrap over players, because one shutdown repeats across all of a player's playoff weeks.

## Results

| Season | Group | Out-weeks Nov–Feb | Out-weeks playoff window | Factor | In-week DNP Nov–Feb → window |
|---|---|---:|---:|---:|---|
| 2024-25 | bottom 10 | 11.1% | 39.7% | 0.68 | 14.8% → 26.4% |
| 2024-25 | rest | 5.4% | 11.7% | 0.93 | 8.5% → 13.7% |
| 2025-26 | bottom 10 | 8.0% | 31.7% | 0.74 | 13.1% → 22.6% |
| 2025-26 | rest | 7.8% | 16.1% | 0.91 | 10.0% → 8.7% |
| Pooled | bottom 10 (43 players) | 9.6% | 35.8% | **0.711** | |
| Pooled | rest (117 players) | 6.7% | 14.0% | **0.921** | |

Both seasons agree. On a 20 V/wk starter, the gap between the groups is about 4 V/wk in playoff weeks. That is about 4× the difference between a 4-game and a 3-game playoff week (about 5% of V, 1 V/wk) and about 2× the full best-to-worst schedule range in [playoff-schedule.md](../2026-10-20/playoff-schedule.md) (9.4%, 1.9 V/wk).

**When live standings can be trusted:** each team's first N games identify this share of the deadline bottom 10:

| N | 10 | 15 | 20 | 30 | 40 |
|---|---:|---:|---:|---:|---:|
| 2024-25 | 70% | 80% | 80% | 90% | 100% |
| 2025-26 | 70% | 80% | 80% | 80% | 90% |

## What `trade.py` does

- `po_avail` splits the teams into the live bottom 10 and the rest, from Sleeper's schedule results, once every team has played 15 games. Before that, every team gets the group mean, 0.851. Sides with fewer than 10 scheduled games are All-Star exhibition teams and are ignored; their codes vary by season.
- `po_mult` = the schedule multiplier × availability. It feeds the playoff-weighted delta, `--suggest --playoff` and the `PO … x` tag, which now shows `= sched x… avail x…`.
- The simulated rotation (`sim_value`) applies the factor in playoff weeks as a whole-week absence: out = 1 − (1 − out) × factor.
- `q31.py` asserts that `trade.po_avail` names the same deadline bottom 10 as the fit.

## Limits

- **Upper bound:** the NBA's May 28, 2026 lottery reform (the "3-2-1" format and fines up to $10M) applies to the 2027 lottery. It may reduce shutdowns this season, so read 0.71 as a ceiling on the effect.
- **Standings are a proxy:** the factor fits deadline standings, but live standings are still noisy in November. Playoff-race context (seeding locked, play-in) is not modeled.
- **In-week DNPs:** the rise in single missed games (for example 13% → 23%) is not applied. It mostly costs a lock roll.
- **Act before the deadline:** the factor matters only for trades made before the deadline, whose date is unconfirmed (#3: week 18 or about 4 weeks earlier).
