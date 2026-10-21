# Playoff schedules in Lock-In (weeks 21-23)

Run October 19, 2026 on the live Sleeper schedule (`api.sleeper.com/schedule/nba/regular/2026`, 1,200 games) via `trade.playoff_profile`. Player teams come from the cached `/players/nba` file. Fantasy playoffs are weeks 21-23. We project 1st, so our games would be weeks 22-23 after a bye; `trade.py`'s playoff-weighted delta uses those two weeks.

**Bottom line**
- **Lock-In flattens schedules.** A 4-game week is worth +3%, a 3-game week -2%, and a 2-game week -10% against a typical 3.4-game week. The best playoff schedule (DAL, PHX, ORL, PHI, MEM, TOR) beats the median by about 3%. The worst (CLE) is 6% short in weeks 22-23.
- **Use it as a tiebreaker only.** On a 20 V/wk starter, the gap between the best and worst schedule is about 2 V/wk, and only in the playoffs. In the top 5 of `--suggest`, no trade moves more than one place. In the top 30, trades move up to 8 places, but only among deals within about 1 V/wk of each other.
- **Our CLE pair is the weak spot.** Harden (21.5) and Allen (14.0) play 3 then 2 games in weeks 22-23, which costs about 2.2 V/wk combined in those weeks. Booker (PHX), LeBron and Edgecombe (PHI), and Barrett and Poeltl (TOR) have top-6 schedules.

## Method

- **Multiplier:** expected locked score in a team's week ÷ a typical 3.4-game week (0.6 × 3 games + 0.4 × 4 games, no B2B), at 40 FP/g. It uses `rebuild_board.lock_values`' optimal stopping with the backtest DNP correction (`gm.play_on`: q = 0.08 per game, 0.12 on the second night of a back-to-back). Games 1-5 score 0.75, 0.90, 0.98, 1.03 and 1.07 against the base: each extra game is one more lock roll, and each roll adds less than the one before.
- **B2B** counts second nights, including Sunday-to-Monday pairs across weeks. A second night costs only about 0.25%, because a missed game mostly removes one roll. **Playoff-weighted delta** (`./trade.py`): the regular-season delta plus Σ ±(m − 1)·V over starters who enter or leave our lineup, where m is the player's mean multiplier for weeks 22-23. The bench term is not weighted.

## All 30 teams (sorted by weeks 22-23)

| Team | Games 21/22/23 | B2B 21/22/23 | Multiplier 21/22/23 | Wk 22-23 | Wk 21-23 |
|---|---|---|---|---:|---:|
| DAL | 4 / 4 / 4 | 1 / 0 / 1 | +3.0% / +3.3% / +3.0% | +3.2% | +3.1% |
| PHX | 4 / 4 / 4 | 1 / 0 / 1 | +3.0% / +3.3% / +3.0% | +3.2% | +3.1% |
| ORL | 3 / 4 / 4 | 1 / 1 / 0 | -2.6% / +3.0% / +3.3% | +3.2% | +1.2% |
| PHI | 3 / 4 / 4 | 1 / 1 / 1 | -2.5% / +3.0% / +3.0% | +3.0% | +1.2% |
| MEM | 4 / 4 / 4 | 1 / 1 / 1 | +3.0% / +3.0% / +3.0% | +3.0% | +3.0% |
| TOR | 3 / 4 / 4 | 0 / 2 / 1 | -2.2% / +2.7% / +2.6% | +2.7% | +1.1% |
| CHA | 4 / 3 / 4 | 1 / 0 / 0 | +3.0% / -2.2% / +3.3% | +0.5% | +1.4% |
| LAL | 3 / 4 / 3 | 1 / 1 / 0 | -2.6% / +3.0% / -2.2% | +0.4% | -0.6% |
| DET | 4 / 3 / 4 | 1 / 0 / 1 | +2.6% / -2.2% / +3.0% | +0.4% | +1.1% |
| NOP | 4 / 4 / 3 | 1 / 1 / 0 | +2.6% / +3.0% / -2.2% | +0.4% | +1.1% |
| BKN | 3 / 4 / 3 | 0 / 1 / 0 | -2.2% / +3.0% / -2.2% | +0.4% | -0.5% |
| CHI | 3 / 3 / 4 | 0 / 0 / 1 | -2.2% / -2.2% / +3.0% | +0.4% | -0.5% |
| SAC | 4 / 4 / 3 | 0 / 1 / 1 | +3.3% / +3.0% / -2.5% | +0.2% | +1.3% |
| OKC | 4 / 3 / 4 | 0 / 1 / 1 | +3.3% / -2.6% / +3.0% | +0.2% | +1.2% |
| NYK | 3 / 3 / 4 | 1 / 1 / 1 | -2.6% / -2.6% / +3.0% | +0.2% | -0.7% |
| ATL | 4 / 4 / 3 | 1 / 1 / 0 | +3.0% / +2.6% / -2.2% | +0.2% | +1.1% |
| LAC | 4 / 3 / 4 | 1 / 0 / 1 | +3.0% / -2.2% / +2.6% | +0.2% | +1.1% |
| WAS | 3 / 3 / 4 | 0 / 0 / 1 | -2.2% / -2.2% / +2.6% | +0.2% | -0.6% |
| MIL | 3 / 3 / 4 | 1 / 0 / 1 | -3.1% / -2.2% / +2.6% | +0.2% | -0.9% |
| GSW | 4 / 3 / 4 | 1 / 1 / 1 | +3.0% / -2.6% / +3.0% | +0.2% | +1.1% |
| SAS | 3 / 4 / 3 | 0 / 1 / 1 | -2.2% / +3.0% / -2.6% | +0.2% | -0.6% |
| HOU | 3 / 3 / 4 | 1 / 1 / 1 | -2.5% / -2.6% / +3.0% | +0.2% | -0.7% |
| BOS | 4 / 3 / 4 | 1 / 0 / 2 | +3.0% / -2.2% / +2.4% | +0.1% | +1.1% |
| DEN | 4 / 4 / 3 | 1 / 1 / 1 | +3.0% / +2.6% / -2.6% | +0.0% | +1.0% |
| UTA | 3 / 3 / 4 | 0 / 1 / 1 | -2.2% / -2.6% / +2.6% | +0.0% | -0.7% |
| IND | 3 / 4 / 3 | 0 / 1 / 1 | -2.2% / +3.0% / -3.1% | -0.0% | -0.8% |
| POR | 3 / 4 / 3 | 1 / 1 / 1 | -2.6% / +3.0% / -3.1% | -0.0% | -0.9% |
| MIA | 4 / 3 / 3 | 0 / 0 / 0 | +3.3% / -2.2% / -2.2% | -2.2% | -0.4% |
| MIN | 4 / 2 / 4 | 2 / 0 / 0 | +2.4% / -10.2% / +3.3% | -3.5% | -1.5% |
| CLE | 4 / 3 / 2 | 1 / 0 / 0 | +3.0% / -2.2% / -10.2% | -6.2% | -3.1% |

The Owner's roster and trade-target figures are in `private/reports/2026-10-20/playoff-targets.md`.

## Cross-check against `reports/2026-10-19/schedule.md`

- **Game counts:** all 90 team-week counts for weeks 21-23 match, as do the league averages (3.53, 3.47 and 3.60). **B2B:** 7 teams differ (DAL, DEN, HOU, MIN, PHI, SAC, TOR), because the old file counted only within-week back-to-backs and this one adds Sunday-to-Monday pairs.
- **Size:** the old "+1 game ≈ +33% for that player" assumed points-league summing. In Lock-In, going from 3 to 4 games is worth about +5.6%, so the old sizing overstated the schedule edge by about 6×. Its ranking still holds.
