# board.txt audit — 2026-10-19

> Archived research. Rankings, injury claims, simulations, and pick advice below are historical. Use the [current league rules](../../README.md#league-rules) and a fresh `./draft.py` run for decisions. OUT players use a bench spot in this league. Old season-total scores and survival percentages are retired.

Source of truth: Sleeper `/players/nba` cached at `/home/rallman/fb-gm/.cache/players-2026-10-19.json`, matched with draft.py's own `norm()`/`load_board()`. Live `./draft.py --top 300` ran clean (pre_draft, Owner slot 1 on the clock): **no "not matched" warnings**, board shows "262 left, 0 taken" out of 263 names. The missing one is Sochan (see below).

## Verdict
Every name matches the right player, there are no duplicates, and the board stays in order. The real problem is the **position text in the notes**: 78 of 263 disagree with Sleeper's `fantasy_positions`, which is what the league uses for lineup slots. Use `board-fixed.txt`. It takes about a minute to drop in and has been verified with draft.py's loader: 272 lines, 0 unmatched, 0 duplicates, 0 position mismatches, and `--test` passes.

## board.txt vs board-fantasypros.txt
`cmp` shows the two files are **byte-identical**. That's expected, since prep-notes says board.txt = board-fantasypros.txt. No action needed.

## Issue counts
| Type | Count | Verdict |
|---|---|---|
| Unmatched names | 0 | — |
| Duplicates | 0 | — |
| Wrong same-name match | 0 (1 at risk: Jaylin Williams) | fix (pin by id) |
| No team in Sleeper (unsigned/waived) | 1 (Jeremy Sochan) | fix (remove) |
| Team in note ≠ Sleeper | 0 real. 3 code spellings differ: PHO/UTH/NOR vs PHX/UTA/NOP | cosmetic, normalized |
| Positions in note ≠ Sleeper | 78 | **fix** |
| On board and Sleeper says Out | 13 | flag. Projected GP often ignores it |
| Two-way contract | 1 (Jonathan Mogbo, 453 FP, last on board) | ignore |
| Sleeper top-200 active players missing from board | 10 | optional (appended, unranked) |
| "last None (None)" text | 12 | cosmetic, changed to "last n/a" |
| FP order / GP×FP/G math | 0 breaks | — |

## Top issues
1. **Giannis note says PF,C. Sleeper says PF only.** He can't fill the C slot. That matters for the pick-20/30 plan if you're counting him as a center.
2. **Scottie Barnes note says C,PF,SF,SG. Sleeper says SF,PF.** He loses C and SG eligibility.
3. **Zion note says C,PF. Sleeper says SF,PF.** He isn't C-eligible.
4. **Guards listed as PG,SG are PG-only in Sleeper:** Luka, Cade, Maxey, Harden, Fox, VanVleet, Suggs, Rollins, Collier, Pippen, Henderson. None of them can fill SG or G-via-SG. For example, Luka + Harden can't cover PG and SG on their own.
5. **Bigs listed as PF,C are C-only in Sleeper:** Porziņģis, Diabaté, Isaiah Jackson, Bagley, Vukcevic, Jackson-Davis, Looney, Ighodaro. They lose PF/F flexibility. Grant Williams is the reverse case: the note says PF,C but Sleeper has him at PF only.
6. **Gains you'd otherwise miss:** Cooper Flagg (PG,SG,SF), LeBron (PG,SF,PF), Julius Randle and Cameron Boozer (PF,C), Kyrie and Morant (PG,SG), Klay (SG,SF,PF). Each is more flexible in Sleeper than the note says. Desmond Bane changes rather than gains: he's PG,SG in Sleeper, not SG,SF.
7. **Brandon Ingram (board #83) is [Out].** He had a partial Achilles repair. On Oct 14 Lue said "it's going to be a while", and there's no timetable ([B/R](https://bleacherreport.com/articles/25504212-brandon-ingrams-new-injury-diagnosed-after-surgery-latest-clippers-stars-timeline-return), [Field Level Media](https://fieldlevelmedia.com/news/clippers-f-brandon-ingram-achilles-heel-to-miss-start-of-season/)), yet FantasyPros projects 64 GP. He's overrated where he sits and works as an IR stash at best. The fixed board's note now says this.
8. **Other Out players still projected near full GP:** Nic Claxton (hamstring, 74 GP), Tobias Harris (calf, 75), Jusuf Nurkić (foot, 68), Bradley Beal (knee inflammation, 65; I found no 2026 news on this, so it's unverified), Isaiah Stewart (ankle, 73), Max Strus (foot, 70), Porziņģis (illness, 63). Already discounted: Butler 44, Mark Williams 29, Sharpe 18. draft.py prints [Out] next to these players, so the Owner will see it. Check the news before taking any of them. Not re-ranked.
9. **Jeremy Sochan has no team in Sleeper** (FA, active). He signed a *non-guaranteed* 1-year deal with POR on Aug 1 ([NBC](https://www.nbcsports.com/fantasy/basketball/player-news/2026-08-01/shams-jeremy-sochan-to-sign-with-trail-blazers)). Sleeper's FA status suggests he was waived, but I couldn't confirm a release. draft.py already hides him, and he's #255 on the board, so it's trivial. Removed.
10. **Jaylin Williams has a same-name free agent** (id 2845, Auburn rookie, FA, Sleeper rank 302, which ranks better than the real one's 338). draft.py's `by_name.setdefault` keeps whichever player comes first in the JSON. Today that's the right one (OKC id 2475, index 269 vs 1042), but that depends on order. The fixed board pins `2475` by id, which `load_board` supports. The root-cause fix belongs in draft.py: prefer players with a team when names collide. I didn't make it because edits weren't allowed.

## Missing fantasy-relevant players
All Sleeper players ranked 1–128 are on the board. The FantasyPros source only projects 264 players. Sleeper top-200 players with teams who aren't on the board: DiVincenzo #129 (Out, Achilles), Raynaud #169 (Out, knee), Aday Mara #184, Brayden Burries #187, Lu Dort #191, Alex Caruso #193, Gradey Dick #196, Tre Johnson #197, Justin Champagnie #199, Mamukelashvili #200. A 140-pick draft ends well before board #262, so the impact is low. They're appended to the end of board-fixed.txt and marked `NO PROJECTION`, so they show up under `--pos` filters instead of only in the search_rank fallback. Optional.

## Teams
After mapping PHO→PHX, UTH→UTA and NOR→NOP, all 262 rostered players' note teams match Sleeper. This includes the offseason moves: Giannis MIA, Harden CLE, Kawhi TOR, LeBron PHI, Jaylen Brown PHI, Davis WAS, Trae WAS, LaMelo MIN, Morant POR and so on. These look surprising, but Sleeper agrees with them. The fixed board uses Sleeper's codes.

## What changed in board-fixed.txt
- Positions in every note are rewritten from Sleeper `fantasy_positions`, in PG,SG,SF,PF,C order.
- Team codes now use Sleeper's spelling.
- Sochan is removed.
- Jaylin Williams is pinned to id 2475.
- Ingram's note now includes his Out status.
- "last None (None)" now reads "last n/a".
- The 10 unprojected players are appended under a comment line.
- FP numbers and ranking order are untouched.

## Not checked
- I didn't re-rank Out players. That needs per-player return dates.
- I didn't verify whether Sleeper's fantasy_positions will change during the season. Sleeper sets them, and draft.py already uses Sleeper's values for slot math, so the board notes were only ever informational.
