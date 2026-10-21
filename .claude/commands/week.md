---
description: Monday war room - game counts, rotation plan, waiver claims, trade ideas
argument-hint: [week]
---

Monday war room for the Sleeper week starting today (or week $ARGUMENTS; if given, pass `--week $ARGUMENTS` to `week` and `matchup`). Lead with a 3-line summary of the actions to take.

1. From week 2 on, run `python3 rebuild_board.py --blend --write` then `./draft.py` (name check) so the board reflects actual results; report big movers. `board.txt` and `board-actuals.csv` change together: ask the Owner to commit both (a `board.txt` without its actuals fails `rebuild_board.py --test` in other clones). Then run `./gm.py changes`, `./gm.py roster`, `./gm.py week`, `./gm.py fa --top 25`, `./gm.py matchup` and `./gm.py standings`. Read `private/notes/managers.md` and the open entries in `private/notes/recommendations.md`. Stop if any command prints `REFUSING`.
2. In parallel, call `scout` (status and rest news for our 14 players and the top free-agent targets) and `league-watcher` (opponent needs, likely trade partners, this week's opponent). Wait for both.
3. **Games and rotation:** each starter's game count and days, starters flagged with 0–1 games, base-lineup changes, and the day-by-day feeds from `./gm.py week` with the expected gain in FP.
4. **Waivers:** claims only where ΔV/wk or this week's ΔE beats the drop by enough to matter. Name the drop for each. With rolling waivers, a claim costs our priority (we're at the position `fa` prints), so spend it only on a clear upgrade; free agents not on waivers are instant adds. "No claim" is fine.
   Stream check: `./gm.py fa`'s "Stream this week" block gives ΔTeam (whole-team gain this week, rotation included) per add/drop. Consider a stream when ΔTeam ≥ ~5 FP and the season ΔV/wk cost is small. A rolling-waiver claim costs our priority. A free agent is an instant add only until his team tips this week; after that he is a waiver claim (`fa` tags him).
5. **Trades (deadline week 18):** first re-check open trade ideas in the log and drop any whose premise changed. Then up to 2 ideas, each checked with `./trade.py "<give>" "<get>"` (or `./trade.py --suggest` for candidates; its acceptance check uses the partner's Sleeper-rank view, a heuristic, so name the selling point for them): partner, opening offer, walk-away price, why it fits both teams, main risk. "No trade" is fine.
6. **Matchup:** opponent and board strength, plus where we stand against the median.
   Use `matchup`'s win odds for lock risk all week: a big favourite prefers safe early locks; a big underdog late in the week waits for upside.
7. Log material recommendations in `private/notes/recommendations.md`; update `private/notes/managers.md` from the league-watcher's proposed lines after checking them.
