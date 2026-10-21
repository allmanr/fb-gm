# Same-night slot reuse: backtest for issue #22

**Update, Oct 20: built at a 3 h gap on the Owner's go-ahead** (`gm.py` `REUSE_GAP`, `reuse`; [#22](https://github.com/allmanr/fb-gm-private/issues/22)).

Run on October 20, 2026. **Verdict: the result is split, so the Owner decides.** At a 3-hour tip gap, reusing a slot on a staggered night adds **+0.60 wins per 20-week season** in random leagues (95% CI +0.43 to +0.77). That clears #9's 0.3 wins gate with room to spare. The FP gain is **+2.86 FP/week** (CI +2.43 to +3.31), just under the 3 FP/week gate set in [#22](https://github.com/allmanr/fb-gm-private/issues/22). On our own roster the gain is +2.58 FP/week, but 25 weeks are too few to separate it from zero (CI −0.92 to +8.24). The cost is about 1.4 extra late-evening swaps a week.

Scripts and output: [`backtest/q22.py`](backtest/q22.py), [`backtest/q22.out`](backtest/q22.out), and the model-world check [`backtest/q22_check.py`](backtest/q22_check.py), [`backtest/q22_check.out`](backtest/q22_check.out). To rerun, use `python3 q22.py 300` in `backtest/`. The first run downloads 2025-26 logs as for the [Lock-In backtest](lockin-backtest.md) and ESPN tip times for all 166 game dates into the gitignored `tips25/`.

## Method

- **Baseline: `gm.py`'s plan.** The base lineup is the best set by expected locked score (`best_lineup`). `gm.rotation` then feeds the bench at most one roll per slot per day.
- **Reuse arm.** After the baseline plan, a bench player who plays that day but feeds no slot can take a slot whose rolls that day all tip at least the gap away from his tip. There are two cases: an early starter or feeder, then him late; or him early, then the slot's late starter returns. Players go best FP/g first, each into the slot with the largest gain in expected locked score. The insertion is greedy, so the result is a lower bound on a joint plan.
- **Gap.** The gap is tip-to-tip, covering the early game's length plus time to decide and swap. NBA games typically run about 2¼ hours (not measured here), so 3 h is the realistic arm: an early 7:00 ET tip finishes around 9:15, before a 10:00 ET tip. 2.5 h is optimistic and 3.5 h is conservative.
- **Inputs.** The model sees only causal FP/g (`q12.causal_ppg`), `gm.play_on` DNP odds, `fantasy_positions`, and ESPN tip times keyed on the player's team. No locks are known before the week.
- **Scores.** *Expected* is the model's value (`stop_value` over each slot's rolls in tip order). *Realized* walks the same lock lines over the real box scores. A DNP scores 0, and an unlocked slot keeps its last roll.
- **Samples.**
  - Our live roster: 13 of 14 active players have 2025-26 logs; the other player adds nothing to either arm. Replayed over weeks 1–25.
  - Random leagues: 300 league-weeks of 10 teams with 14 players each, drafted in 14 ten-rank bands of the top 140 by FP/g (40+ games).
  - Wins are H2H plus the median game. One team switches to reuse while the other nine stay on the baseline.
  - CIs bootstrap over weeks (our roster) and over league-weeks (random leagues).

## Results

| Gap | Extra rolls/wk | Expected FP/wk | Realized FP/wk | Wins / 20 wk |
|---|---:|---:|---:|---:|
| 2.5 h | +2.16 | +1.19 [+1.09, +1.31] | +4.33 [+3.68, +4.99] | +0.87 [+0.69, +1.06] |
| **3.0 h** | **+1.37** | **+0.73 [+0.68, +0.78]** | **+2.86 [+2.43, +3.31]** | **+0.60 [+0.43, +0.77]** |
| 3.5 h | +0.71 | +0.39 [+0.35, +0.43] | +1.51 [+1.19, +1.85] | +0.28 [+0.17, +0.41] |

Random leagues, 3,000 team-weeks. Our roster at 3 h: +1.52 rolls/wk, expected +0.80 [+0.53, +1.11], realized +2.58 [−0.92, +8.24].

Staggered nights are common: on 131 of 162 multi-game nights in 2025-26, the first and last tips were at least 3 h apart. The gain is small anyway, for two reasons. An extra roll needs a bench player whom no idle slot could take, which happens about 1.4 times a week. And an extra roll adds little to a slot that already has 4–6 rolls.

## Realized gains are about 4× the model's

The model expects +0.73 FP/week at 3 h, but real scores deliver +2.86. [`q22_check.py`](backtest/q22_check.py) replays the same plans three ways (60 league-weeks):

| Scores | Gain per team-week |
|---|---:|
| Model expectation | +0.76 |
| Model-world draws (`gm.draws` at `play_on` odds), 20 per plan | +0.77 |
| Real 2025-26 box scores | +3.39 |

The code agrees with its model. The difference comes from the real scores. The inserted players themselves scored *below* the model: they missed 14.5% of their games and averaged 25.1 FP against 27.0 expected. So the realized gain comes from how one more roll changes the lock path on real score sequences, not from the extra game's own points.

The likely cause is that real per-game scores have a heavier right tail than the model's normal grid, which makes an extra roll worth more than the model thinks. This is unverified. If true, the model also undervalues the rotation's ordinary feeds. That would matter for #12's calibration, but it doesn't change any lock line here.

The model's baseline is otherwise calibrated: realized is 97% of expected once players who missed the whole week are excluded. In live use, `gm.py` would know those players were out.

## Decision for the Owner

- **For building:** the wins gain clears #9's gate even at a 70% swap rate (about +0.42 wins, scaling roughly linearly). The planner already uses the needed data (ESPN tips), and the extra workload is light at about 1.4 swaps a week.
- **Against:** it misses the 3 FP/week gate set before the test. The gain rests on real-score behaviour the model doesn't capture, measured on one season. The swaps happen late in the evening, after the early game ends. It also touches the lock path: the early score's deadline moves to the late tip that same night.
- **Recommendation:** build it at a 3 h gap, since the wins evidence is strong and the cost is small. The lock-path change ships with the tests listed in #22.

## Limits

- The gap is a fixed tip-to-tip rule, not each game's real end time. Overtime and long games can break a 3 h gap occasionally, so the live tool should confirm the early game is final before suggesting the swap.
- The insertion is greedy on top of a greedy plan. A joint plan could gain a little more.
- The gains assume the Owner makes every swap. They scale about linearly with the share of swaps made.
- One season of real scores. A heavy-tail effect should hold from season to season, but this backtest doesn't test that.
- Mid-week NBA trades: a player's tip comes from his team that night, falling back to his team that week.
