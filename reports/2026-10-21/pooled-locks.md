# Pooled bench locks: 2025-26 backtest (issue #26, PR #27)

**Verdict: keep it.** Pooled locks add +4.2 FP per team-week and +0.80 wins per 20 weeks in random leagues (95% CI +0.56 to +1.04). On the Owner's roster the mean is the same, +4.2 FP/wk, but 25 weeks is too few to separate it from zero.

## Method

[`q26.py`](../2026-10-20/backtest/q26.py) replays each week night by night on the real 2025-26 box scores, from the same base lineup in every arm, with no same-night reuse:

- **lane:** the pre-#27 plan (`gm.rotation` without its seat-the-rest pass). Each score is judged on its own slot.
- **seated:** the merged plan, which seats every bench player who fits an idle slot. Scores are still judged on their own slot.
- **pooled:** the merged plan, with the night's bench scores decided by `gm.joint_locks`, as `gm.py lock` does.
- **hindsight:** the best legal 9 of each player's best game. Only perfect knowledge of the scores reaches it.

A locked player's later planned games are dropped from every slot. Inputs are q22's: causal FP/g, `play_on` DNP chances and current Sleeper positions. Rosters are the Owner's roster over weeks 1-25 and 300 random league-weeks (10 teams from ten-rank bands of the top 140). Wins switch one team and leave the other nine on lane. The run takes 34 s ([output](../2026-10-20/backtest/q26.out)).

## Results

| Arm vs lane | Owner, 25 weeks | Random leagues, 300 × 10 |
|---|---|---|
| seated | +0.0 FP/wk | +0.08 FP/wk [−0.00, +0.18] |
| pooled | +4.2 FP/wk [−3.0, +10.8], 0.52 via locks/wk | +4.24 FP/wk [+3.64, +4.83]; +0.80 wins/20 wk [+0.56, +1.04] |

Lane scores 440.5 FP/wk for the Owner (q22's baseline gives the same 440.5) against a hindsight 534.1. Pooling closes 4.5% of that gap. Hindsight isn't a reachable target: it picks each player's best game after the fact.

Seating alone adds nothing. The gain comes from deciding bench scores jointly, and the extra seats only give the joint call more scores to choose from.

`joint_locks` matched an exhaustive search of every lock set in 3,000 of 3,000 random cases, so it is exact for its objective. The policy as a whole is a heuristic: one-hop reach, and each slot's future valued from its own planned games.

## Worst week

Week 15, −47.5 for the Owner. McCollum scored 60.5 on Monday in Booker's PG slot. Pooling locked it via Allen's UTIL (line 48.5 + 1) rather than in place (58.1). That moved Booker's slot to UTIL and benched Allen for the week. Booker then sat every game, and Allen scored 103.5 on Sunday. The call was right on the projections (Booker 46.5 FP/g, Allen 35.5), so this was a bad outcome, not a bug. The replay never moves a benched starter into another slot, which makes it conservative for pooled. A live Owner could still have played Allen in Booker's idle slot.

## Limits

- Scores are decided on their game night, not deferred to the slot's next tip.
- No same-night reuse in any arm.
- Positions are 2026 Sleeper eligibility.
- The model expects less than real scores deliver (q22_check). These are realized numbers only.
