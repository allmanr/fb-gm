---
description: Daily Lock-In brief - today's starts, pending locks with thresholds, and swaps
argument-hint: [YYYY-MM-DD]
---

Daily brief for today (or the date given: $ARGUMENTS, passed as `--date YYYY-MM-DD`). Answer in under 15 lines; only what's actionable or new.

1. Run `./gm.py changes`, `./gm.py roster`, `./gm.py lock` (pending calls from box scores) and `./gm.py week`, adding `--date YYYY-MM-DD` before the command if a date was given. Stop if any prints `REFUSING`.
2. If a starter or today's feeder has a status tag, a rest-risk back-to-back, or news since yesterday, call `scout` with that player list. Rerun `./gm.py lock "<player>" <score> --play P` if the scout's evidence changes a play probability.
3. Report, in this order:
   - **Lock now:** each pending LOCK call with score vs wait value. Deadline: the one `gm.py` prints, the slot's next tip in CT (date-level when tip times are missing: check the tip time in Sleeper). For a LOCK via, give the move (who goes into which slot, who goes to the bench) and its deadline. Also list WAITs with the threshold. Ask the Owner which locks they made since the last brief, and record each with `./gm.py lock "<player>" <score> --commit` before planning, so `week` and `fa` stop feeding those slots.
   - **Tonight's lock lines:** the `Lock lines` row of `./gm.py week` (score that should be locked for each slot playing today). Bench players' "via" lines are shared: the best bench score takes the lowest line it reaches.
   - **Before tip today:** players who must be in a starting slot (starters playing today plus the rotation plan's feeds for today, as "move X into SLOT for Y").
   - **Fix:** any `Out` player on the bench, IR-eligible player not on IR, empty slot, or league move that matters.
   If nothing is actionable, say "Nothing actionable today."
4. Log any material recommendation in `private/notes/recommendations.md`.

Stream check: `./gm.py fa`'s "Stream this week" block gives ΔTeam (whole-team gain this week, rotation included) per add/drop. Consider a stream when ΔTeam ≥ ~5 FP and the season ΔV/wk cost is small. A rolling-waiver claim costs our priority. A free agent is an instant add only until his team tips this week; after that he is a waiver claim (`fa` tags him).

Lock lines are matchup lines in the live week: `lock` and `week` already lower them as a favourite and raise them as an underdog, from every team's current state. Before the lock calls, ask the Owner which opponent locks Sleeper's matchup view shows and record each with `./gm.py lock "<their player>" <score> --commit`. Quote the matchup line. `week` adds the EV line when they differ by 0.5 FP or more, and `lock` always prints both. Call a 1–2 FP gap a lean, since the win model is overconfident.

Lock rule of thumb when `gm.py` isn't handy (2025-26 backtest): lock at about 0.92× his FP/g with 1 game left, 1.1× with 2, 1.2× with 3–4.
Subtract 0.03× if his next game is the second night of a back-to-back.
If his next game is ruled out, count only the games after it.
