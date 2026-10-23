# Win-odds lock calls: backtest for issue #9

> **Superseded Oct 22, 2026:** the Owner asked for matchup-aware lines, so this rule is now built: `gm.py lock` and `week` use matchup lines in the live week (README, "Matchup lines" in CLAUDE.md). The numbers below still describe its expected size.

Run on October 20, 2026. **Verdict: don't build it; close [#9](https://github.com/allmanr/fb-gm-private/issues/9).** A lock rule that maximizes P(win H2H) + P(beat median) gains **+0.24 wins per 20-week season** over `gm.py`'s EV thresholds (95% CI +0.18 to +0.30). The gain is real but below the ~0.3 wins/season gate set before the test. It is also an upper bound for live use: the sim knows every team's slot states exactly, and live in-week scores and win odds are not yet trusted ([#7](https://github.com/allmanr/fb-gm-private/issues/7), [#12](https://github.com/allmanr/fb-gm-private/issues/12)).

Script and output: [`backtest/q9.py`](backtest/q9.py), [`backtest/q9.out`](backtest/q9.out). Rerun with `python3 q9.py 4000` in `backtest/` (about 9 minutes; logs download as for the [Lock-In backtest](lockin-backtest.md)).

## Method

- **League-week:** a random 2025-26 week (Sleeper weeks 1–25). The top 90 players by FP/g (40+ games) who play that week are split into nine 10-rank bands, and each of 10 teams gets one player per band. Pairs play H2H, and every team plays the league median.
- **Slots:** one player per slot, no bench rotation, no positions. Each slot rolls his real games that week (DNP = 0). An unlocked slot scores its last game.
- **Model inputs:** causal FP/g (2024-25 prior plus games so far, `q12.causal_ppg`), the board's fitted score distribution, and `gm.py`'s DNP chances (`play_on`: 0.08, 0.12 on a back-to-back's second night). No new constants.
- **EV policy:** lock when the score reaches `stop_value` of his remaining games. All teams use it in the baseline.
- **Win-odds policy:** one team at a time switches; the other nine stay on EV. After each game day, each of its unlocked slots that just played with games left picks LOCK or WAIT to maximize P(win H2H) + P(beat median). Each slot's state is its locked score or its EV continuation moments (`gm.stop_moments`). Team totals are normal, as in `gm.win_odds`. P(beat median) is computed exactly under that model: at least 5 of the other 9 teams finish below us.
- **Sample:** 4,000 league-weeks × 10 teams = 40,000 paired team-weeks, 577,732 lock decisions. The 95% CI is a bootstrap over league-weeks.

## Results

| Pre-week H2H odds (model) | Team-weeks | Gain, wins per 20 weeks | 95% CI |
|---|---:|---:|---|
| All | 40,000 | **+0.240** | +0.181 to +0.301 |
| Favourite (≥ 60%) | 8,916 | +0.295 | +0.169 to +0.424 |
| Even (40–60%) | 22,168 | +0.189 | +0.109 to +0.270 |
| Underdog (< 40%) | 8,916 | +0.312 | +0.160 to +0.461 |

- The win-odds rule disagrees with EV on 4.4% of decisions.
- **Direction of disagreements** (300-week diagnostic run, not committed): favourites lock early more often than they wait past EV (2.4% of decisions vs 1.8%). Underdogs mostly wait past EV (0.8% vs 5.0%). Even weeks lean toward waiting (1.1% vs 3.4%). This matches the hand rule in `/daily` and `/week`.
- **Sanity check:** baseline wins per team-week are 0.998 (expected 1.0 in a zero-sum league).

## Why it stops here

- **The gain is under the gate.** +0.24 wins/season is about one extra win every four seasons. The CI's upper end only reaches the 0.3 bar.
- **Live use would earn less.** The sim reads every team's state perfectly. Live, each call would depend on Sleeper's in-week matchup points (unverified, #7) and on `matchup`'s normal model, which is known to be overconfident (#12). The rule also only helps when the Owner runs it before every lock.
- **The build is not small.** It needs all 10 teams' slot states and an exact median calculation in `gm.py lock`, plus tests.

**Keep:** the `/daily` and `/week` hand rule. The backtest confirms its direction: lock safe scores early as a big favourite, and wait for upside as an underdog. Its size in league points is small.

## Limits (ceiling)

- No bench rotation: bench feeds add lock rolls, so the gain could be somewhat larger. Not measured.
- A WAIT is valued as an EV continuation, and same-night slots are decided one at a time rather than jointly. Exact slot distributions and joint decisions could add a little.
- Teams are built from bands and are close in strength. A league with wider gaps has more favourite and underdog weeks, where the gain per week is higher.
- Reopen #9 only if one of these changes the picture, for example a rotation-aware rerun above 0.3 wins/season after #7 and #12 are settled.
