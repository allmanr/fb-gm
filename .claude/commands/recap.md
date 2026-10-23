---
description: Weekly recap after Sunday's games - result, lock review, standings, notes
argument-hint: <week just finished>
---

Weekly recap for week $ARGUMENTS (the week that just ended; run it after Sunday's games or Monday morning). Keep it short.

1. Run `./gm.py matchup --week N`, `./gm.py review --week N` (per slot: points counted vs the lock policy replayed on the same box scores vs hindsight, with each leak's cause), `./gm.py --date <that Sunday> lock --week N` (each starter's game log with what the lock math said), `./gm.py standings` and `./gm.py changes --no-write`. Stop if any prints `REFUSING`.
2. **Result:** H2H win or loss and the median-game result, with the slots that decided it.
3. **Locks reviewed:** from `review`, the week's counted vs policy vs hindsight totals and the slots that leaked most. Name avoidable mistakes (a lock below the line, no lock recorded, a missed feed) separately from bad luck (DNPs, a late game that beat a correct lock). `review` replays the EV policy. A lock it flags below the line was the policy if it reached the matchup line `gm.py` gave at the time (check the recommendations log), so call it a matchup lock, not a mistake. Likewise, a WAIT on a score above the EV line was policy only if the score was also below that matchup line. A score at or above the matchup line that wasn't locked is a missed lock. Feed adherence prints as unknown: ask the Owner which feeds they made.
4. **Standings:** our place, the playoff line (top 6) and bye race (top 2).
5. **League:** call `league-watcher` for the week's moves and proposed manager-note lines. Check them, then add dated facts to `private/notes/managers.md`.
6. **Recommendations:** for each open entry in `private/notes/recommendations.md`, record the Owner's decision (ask if unknown) and the outcome so far. Judge the decision separately from the result. Append `review`'s outcome line as the week's execution entry.

7. **Back up** `private/` (CLAUDE.md, Private data).

End with the two or three things that matter for next week.
