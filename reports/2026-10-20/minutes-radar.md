# Minutes-trend radar backtest

Run October 20, 2026 for [issue #11](https://github.com/allmanr/fb-gm-private/issues/11), part 2. It asks whether a player whose last-3-game minutes jump above his season average beats the in-season blend (`rebuild_board.blend`, k = 6.5) over the next two weeks. Script and output: [`backtest/minutes_radar.py`](backtest/minutes_radar.py) and [`backtest/minutes_radar.out`](backtest/minutes_radar.out). Rerun with `python3 minutes_radar.py` in `backtest/`. It takes about 10 seconds and downloads missing 2023 and 2024 Sleeper logs into `.cache/` on first use.

**Verdict: keep the radar, threshold 8 minutes.** The flag predicts that the blend is too low. `gm.py fa` now lists free agents with last-3 min/g at least 8 above their season average, after 6 or more games, with FP/minute.

## Method

- **Data.** Sleeper game logs (`rebuild_board.game_logs`) for 2025-26. 2024-25 is the out-of-sample check.
- **Blend prior.** The player's previous-season FP/g (10+ games, k = `BLEND_K`). Players without a prior season use `NO_PRIOR_PPG` at `NO_PRIOR_K`, as `season_actuals` does for off-board adds.
- **Event.** After a game, with 6 or more games played: last-3 min/g minus season-to-date min/g (last 3 included) ≥ T.
- **Declustering.** Each player counts at most once per 14 days, at the first trigger.
- **Population.** Blend prediction ≤ 35 FP/g (waiver range; replacement is about 27).
- **Target.** FP/g over his games in the next 14 days. At least 3 games are required.
- **Residual.** Target minus blend. The 95% CIs come from a bootstrap that resamples players.
- **Alternative predictor.** Last-3 min/g × season FP/minute. Shrinking FP/minute toward the blend's rate changed RMSE by less than 0.1.

## Results

Residual = target − blend, in FP/g. Baseline = every eligible player-game, declustered the same way.

| Group | 2025-26 events (players) | Residual [95% CI] | RMSE blend → alt | 2024-25 events | Residual [95% CI] | RMSE blend → alt |
|---|---|---|---|---|---|---|
| Baseline | 2848 (444) | +0.98 [+0.61, +1.36] | 7.43 → 7.64 | 2753 | +0.98 [+0.68, +1.30] | 7.38 → 7.73 |
| Jump ≥ 4 | 1071 (362) | +3.78 [+3.24, +4.32] | 8.81 → 8.24 | 1085 | +3.37 [+2.82, +3.86] | 8.28 → 8.00 |
| Jump ≥ 6 | 672 (276) | +4.88 [+4.17, +5.66] | 9.46 → 8.56 | 678 | +4.39 [+3.80, +5.05] | 9.01 → 8.37 |
| **Jump ≥ 8** | **399 (195)** | **+6.35 [+5.40, +7.23]** | **10.33 → 8.61** | **413** | **+5.75 [+4.87, +6.69]** | **10.12 → 8.94** |
| Jump ≥ 10 | 229 (132) | +7.32 [+6.09, +8.52] | 10.82 → 9.05 | 225 | +6.93 [+5.77, +8.05] | 11.39 → 10.31 |
| Jump ≥ 12 | 119 (78) | +8.50 [+6.87, +10.15] | 11.49 → 8.75 | 130 | +7.50 [+6.01, +8.95] | 11.22 → 10.24 |

- **The effect is real and replicates.** At 8 or more minutes, flagged players beat the blend by about 6 FP/g, about 5 more than the baseline. Both seasons agree, and every threshold's CI excludes the baseline.
- **The effect grows steadily with the jump; no threshold stands out.** 8 balances size and volume: about 400 events a season across the whole NBA (fewer once rostered players are removed). At 6 there are 1.7× as many events, with a 1 FP/g smaller edge.
- **For flagged players, L3 minutes × FP/minute beats the blend** (RMSE −1.2 to −1.7), but it runs 2.5 to 3.1 FP/g high because minutes partly fall back. The truth sits between the two, closer to the minutes-based number. For everyone else the blend is better (baseline row), so the radar is a flag, not a new projection.

## Limits

- The test counts all players in the waiver range, not only free agents in this league. A rostered player can't be added, so the per-league volume is lower.
- The 3-game target floor favors players who stay healthy. It applies equally to the baseline.
- The prior is last season's FP/g, not the frozen board projection, the same proxy `fit_lockin.py --fit-blend` uses.
