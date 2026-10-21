# Per-game context means: 2025-26 backtest (issue #32)

**Verdict: don't build; closed.** Adjusting lock lines for the opponent and for teammates who are out changes nothing: **+0.00 FP/wk [−0.65, +0.67], +0.04 wins/20 wk [−0.20, +0.29]**. The build gate is 0.3 wins per 20-week season. This was the optimistic version, so a realistic one would do no better.

## Method

[`q32.py`](../2026-10-20/backtest/q32.py) fits a context model on 2024-25 and replays 2025-26 ([output](../2026-10-20/backtest/q32.out), 40 s).

- **Residual:** a game's score minus the player's running FP/g. The running FP/g starts from the prior season's mean, weighted at up to 10 games, or 30 FP/g at weight 5 without a prior.
- **Opponent:** the opponent's running mean residual allowed before that date, shrunk as sum ÷ (n + 150).
- **Teammates out:** the running FP/g of teammates scoring 25+ FP/g who have a DNP row in that game, times the player's share of his team's playing FP/g. His own DNP is excluded. Before that fix a leak gave −3.15 FP/wk; `q32.py` now asserts against it.
- **Fit:** OLS on centered features, so the average shift is 0, among players at 25+ FP/g.
  - 2024-25: opponent coefficient 1.32, teammates coefficient 0.23 (R² 0.017).
  - 2025-26, refit for reference only: 1.49 and 0.23 (R² 0.026).
  - The 2024-25 coefficients explain 2.5% of 2025-26's variance. The mean |shift| is 1.7 FP, and 7.6% of games shift by 4 FP or more.
- **Replay:** q26's pooled-lock replay with the same plan and base lineup. Lock lines use `fpg + shift` per game, on a 0.5 FP grid, instead of the weekly FP/g. Random 10-team leagues, 300 league-weeks. For wins, one team switches to the context arm and the others stay on pooled. `q26.py`'s own output is unchanged.
- **Optimistic:** a teammate's DNP counts as known at every earlier decision that week. In practice it's known only from the injury report near tip.

## Why it doesn't help

The effects are real and replicate across both seasons, but they are small next to game-to-game noise (residual SD about 14.6 FP). A 1.7 FP shift in a future game moves its slot's wait value by less than that and flips few lock calls. Each flipped call gains only the narrow margin it was decided by. The second night of a back-to-back has no scoring effect (+0.04 FP in the issue's sizing), so the existing DNP-only treatment stands.

## Not tested

- **Context in the base lineup and rotation:** it would use the same weak signal, so expect the same null result.
- **Betting lines:** ESPN's scoreboard drops odds once games finish, so they can't be backtested.

Reopen only with a materially stronger per-game predictor, such as minutes projections or player props, that can be backtested.
