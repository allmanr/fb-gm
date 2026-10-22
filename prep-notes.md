# Project notes (league drafted 2026-10-19)

Agents: read **League rules** once at session start; the rest is reference. The [README](README.md) explains how the Owner uses the assistant. League-specific records (the draft result, all rosters, scouting, manager notes, recommendations) are private: `private/draft-night.md` and `private/reports/2026-10-19/draft-retro.md` (see the README's [Private data](README.md#private-data)). [Earlier reports](reports/README.md) are archived research; don't load them unless asked.

## League rules

These rules still apply. The draft result and the archived pre-draft pick plan are in `private/draft-night.md`; they no longer drive decisions.

- **IR rule (checked in league settings):** IR takes only status IR, Sus or DNR, not Out. An OUT player takes a bench spot. Check the player's live Sleeper designation before assuming IR eligibility. The archived IR-stash advice is void.
- **Weekly format correction:** Sleeper counts one game per starter per week. In Lock-In, choose the finished game before the next game starts; a lock is irreversible. More NBA games provide chances, not additive scores. GP × FP/game is no longer our draft objective. Source: https://support.sleeper.com/en/articles/6522833-lock-in-mode-details
- **After the draft:** a player must start the game in your starting lineup for you to lock that score. If you never lock a score, Sleeper uses the team's final game of the week, which can be zero if the player sits. The saved board estimates opportunities; it does not manage lineups or locks for you. Source: [Sleeper's Lock-In rules](https://support.sleeper.com/en/articles/6522833-lock-in-mode-details).
- **Value versus market:** board order estimates weekly lock-in surplus under our scoring; ECR and Sleeper's rank measure different things. The room drafted close to Sleeper's rank, which is why `trade.py` judges acceptance by that view. Within a two-point value tier, prefer roster fit; no blanket center or multi-position bonus.
- **Eligibility:** Sleeper `fantasy_positions` decides slots (`gm.py roster` prints them). Giannis, Zion, Barnes are not C. Luka, Cade, Maxey, Harden, Fox are PG only. Flagg PG/SG/SF, LeBron PG/SF/PF, Kyrie and Morant PG/SG.
- **Opponents:** this room has no NBA history before 2026. Judge managers from `private/notes/managers.md` (dated facts kept apart from inferences) and live transactions (`gm.py changes`), not from NFL habits.
- **Playoff schedule:** weeks 21–23, 6 teams, top 2 bye. Extra games are additional lock opportunities, not extra counted games: a 4-game week is worth only about +3% over a typical week and a 2-game week about −10% ([playoff schedules](reports/2026-10-20/playoff-schedule.md)). Schedule alone rarely justifies moving a player across value tiers.
- **Board notes:** T = approximate two-point weekly-value tier; V = expected weekly lock-in surplus above a matched-schedule healthy replacement (one game kept per week); FP/g = adjusted custom-scoring projection before bounded ECR calibration; ECR = imported ESPN points consensus (rank semantics unverified). GP and season FP remain visible as reference. Actual player positions/status come from the live Sleeper display. `cal X/g` follows the raw FP/g only when the ECR-calibrated FP/g behind V prints differently, and `gm.py` uses it (a blended `-> X/g` still wins).

**Projection-risk rule:** When a displayed ECR review says RISK, prefer a proven peer within the same weekly-value tier. Rookie starting roles support upside, not a promise of the projected production. Brown remains minutes-limited; Lively is uncertain bench coverage. Kevin Porter Jr. is excluded pending a confirmed NBA role.

## Change record, October 19 weekly-value rebuild

The board now ranks estimated weekly lock-in contribution above replacement instead of projected season totals. The scoring weights were already correct. The error was using all NBA games as the draft objective when Sleeper counts one game per starter each week.

This work changed our local draft advice. It did not change Sleeper league settings or make any picks.

| File | Change |
|---|---|
| `board.txt` | Reordered 272 players. Added value tiers, weekly lock-in surplus estimates, expert consensus ranks, and OUT bench warnings. Retained original per-game projections and season totals as reference |
| `board-inputs.csv` | Added an editable snapshot of projections, GP assumptions, expert ranks and dispersion, estimated scoring differences, Sleeper positions/status, and news notes. `original_rank` records the board before this rebuild |
| `rebuild_board.py` | Added deterministic preview, rebuild, and offline checks using 2025-26 Sleeper optimal-stopping lock-in expectations, matched-schedule replacement, and bounded expert adjustment |
| `fit_lockin.py` | Added rerunnable stdlib fitter reproducing `WEEK_GAMES`, `CV_A`, and `CV_B` from 2025-26 Sleeper weekly game logs |
| `prep-notes.md` | Documented the model, its sources, ECR sensitivity, revised the pick plan, and retired the old season-total simulation conclusions |

The owner supplied `FantasyPros_2026_Draft_ALL_Rankings.csv`. We used that export as expert input. `board-fantasypros.txt` remains the original converted projection source. Both are archived privately in `private/reports/2026-10-19/sources/` (the export is FantasyPros data, not ours to republish); `board-inputs.csv` holds the values the tools use.

The model changes are:

- Price optimal sequential stopping over each week's scheduled games (`WEEK_GAMES` and mean-dependent game CV fitted from 2025-26 Sleeper logs via `fit_lockin.py`).
- Penalize missed fantasy weeks more than isolated rest games while still pricing the lost lock-in roll when a player misses single games within a week.
- Count production above a matched-schedule healthy replacement level (`141st` projected player by FP/g, `~26.9/g`). Average over dispersed missed-game counts before taking positive surplus so a replacement-level player has zero surplus (`0.000/wk`). Add an opportunity-cost deduction for current OUT players because this league does not let them use IR.
- Convert expert ranks into a points-based prior, adjust for the difference between ESPN and our scoring, and limit its influence. Reduce the influence further when experts disagree widely.
- Keep positional decisions at pick time. Use actual Sleeper eligibility and remaining roster slots within value tiers. Remove the automatic second-center target after taking Jokić.
- Retire old draft-survival percentages and simulation score comparisons. They were not validated for the new weekly objective.

Selected rank changes, verified against the saved input snapshot and rebuilt board (`original_rank` -> initial weekly rebuild `b8ae63e` -> Lock-In stopping candidate `198b5b2` -> pre-haircut `P4` `d02d007` -> current board):

| Player | Season-total rank (`original_rank`) | Initial weekly (`b8ae63e`) | Lock-in (`198b5b2`) | Pre-haircut `P4` (`d02d007`) | Current rank |
|---|---:|---:|---:|---:|---:|
| Nikola Jokić | 1 | 1 | 1 | 1 | 1 |
| Anthony Davis | 19 | 13 | 15 | 15 | 15 |
| Paolo Banchero | 21 | 16 | 16 | 16 | 16 |
| Jalen Brunson | 18 | 20 | 18 | 18 | 18 |
| Tyrese Haliburton | 23 | 18 | 19 | 19 | 42 |
| Alperen Şengün | 22 | 21 | 20 | 20 | 19 |
| James Harden | 16 | 22 | 21 | 21 | 20 |
| Kevin Durant | 17 | 23 | 22 | 22 | 21 |
| Deni Avdija | 20 | 24 | 23 | 23 | 22 |
| Scottie Barnes | 26 | 29 | 27 | 26 | 26 |
| Joel Embiid | 44 | 26 | 26 | 27 | 25 |
| LeBron James | 48 | 19 | 30 | 33 | 32 |
| Kawhi Leonard | 51 | 25 | 34 | 36 | 35 |

Comparison against `198b5b2`: among players in either version's top 100 or top 140, **zero players move by 5 or more places** when switching from hindsight per-realized-k replacement (`198b5b2`) to matched-schedule pre-dispersed-absence replacement (`P4`). The only moves of at least 2 places involving either top 140 are LeBron James (`#30 -> #33`, `-3`), Kawhi Leonard (`#34 -> #36`, `-2`), and Bobby Portis Jr. (`#140 -> #142`, `-2`).

Verification completed:

- `python3 rebuild_board.py --test` passes. The saved board exactly matches the builder's output from the current input CSV, and healthy replacement-level surplus is zero within `1e-9`.
- `python3 fit_lockin.py --test` passes, reproducing `WEEK_GAMES = {1: 16, 2: 97, 3: 302, 4: 331, 5: 6}` exactly and `CV_A = 1.2923, CV_B = -0.2469` (within `0.0003` of `1.292, -0.247` across `151` players).
- `./draft.py --test` passes, including behavioral render tests for next pick 21 (`21–29` window), next pick 30 (`32–49` window), final pair `130/131` and completed draft (`140` picks, no window), `T# V+#.#` / `NO PROJ` positional footer rendering, and `DO NOT DRAFT` board exclusions. The live display loads the new order with 271 active players matched and assigned to an NBA team in Sleeper plus 1 excluded player (Kevin Porter Jr.).
- The live league scoring was checked against a literal box score. A player with 20 points, 10 rebounds, 5 assists, 1 steal, 1 block, 3 turnovers, 8-of-15 field goals, 2-of-3 free throws, and 2 made threes earns 48 fantasy points.

The input CSV is a snapshot. Running `rebuild_board.py --write` does not refresh injuries, reimport a changed expert export, or recalculate the original stat projections. Update the input CSV before rebuilding when assumptions change. The live assistant refreshes picks and availability separately; a new Sleeper injury designation does not automatically change the saved board's value estimates.

## How board.txt is ranked now

The Oct 19 weekly-value rebuild supersedes sorting by season totals. The frozen source inputs are `board-inputs.csv`; run `python3 rebuild_board.py` to preview, `--write` to rebuild, and `--test` for offline checks. The owner's imported `FantasyPros_2026_Draft_ALL_Rankings.csv` supplies expert ranks and dispersion. The builder preserves 262 projection records plus 10 explicitly unprojected names. One projection record, Kevin Porter Jr., is excluded from drafting and all model baselines pending a confirmed NBA role.

- Keep the prior custom-scoring per-game projections, GP corrections and news notes. Replacement is the 141st projected player by FP/game, about 26.9 after the final availability corrections, because 140 players are rostered. This is a rough universal baseline; use roster/position fit when picking.
- **Lock-in model (Oct 19, Sleeper 2025-26 per-game logs, reproducible via `fit_lockin.py`):** each week a starter keeps one game, chosen by optimal stopping (lock if the score beats the expected value of waiting). Games per team-week last season: `1:16, 2:97, 3:302, 4:331, 5:6`. Per-game FP uses a normal approximation with `CV = 1.292 − 0.247·ln(FP/g)` (`≈0.45` at 30 FP/g, `0.29` at 60). This pooled approximation is a ranking assumption, not a per-player accuracy guarantee. Player-specific variance beyond that is **not** a stable trait (split-half reliability `0.07–0.30`), so there is no per-player ceiling premium. Missed games: share `c` of them remove whole weeks; the rest remove single games, i.e. lock-in chances (binomial). Default `c=0.5`; LeBron `0.15`, Kawhi `0.25`, Embiid/Claxton/Porzingis `0.65`, Ingram/Butler `1`. All editable inputs.
- Use expert ranks conservatively in points space (**ECR rank semantics unverified**). Build an ESPN FP/game curve from our projected players. At each player's ECR, interpolate a prior and add that player's custom-scoring premium. The premium versus ESPN is `0.5*REB - 1.5*(STL+BLK) + FTM` per game. FTM is estimated algebraically from the existing raw custom FP, source PTS/3PM/FG%/FT%, and other counting stats; it inherits the original shooting-attempt approximation. This is not a fresh independent projection source.
- Expert prior weight is at most 25%, reduced to `0.25/(1+(expert SD/15)^2)`, and the final per-game correction is capped at ±2. Tatum/Haliburton/Kyrie's large expert disagreement therefore has little influence; their current returns are independently checked below. Rank numbers are never simply averaged.
- **Matched-schedule replacement proxy (`P4.2`):** `surplus = (1 − whole_week) · Σ_n P(n) · max(0, E_k[L_k | n] − L_n(rep))`, and `V = max(0, surplus − bench cost)`. Dispersed missed games (`k`) are averaged before taking the positive part against a healthy replacement (`141st` eligible FP/g, currently `~26.9/g`) facing the same weekly schedule count `n`, while known whole-week absences remain replaceable. This is a ranking proxy with schedule-known start/sit, an assumed available replacement, and no shared bench constraint—not a guarantee of achievable points. Current OUT players cannot use IR here; their bench cost is `(1 − usable_week_share)` times the 91st player's locked surplus. Players below replacement are ordered by availability-adjusted per-game output; the 10 unprojected names stay flagged at the end.
- Two-point V tiers are approximate judgment bands, not confidence intervals. No invented player-specific boom/variance premium or perfect hindsight best-game projection. The model uses the league-wide empirical schedule distribution rather than team-specific weekly schedules or playoff-only weeks. Use live news, lineup matching, opponent needs and opportunity cost within tiers.
- **In-season blend (`--blend`, fit by `fit_lockin.py --fit-blend`):** after `n` games, FP/g = `prior + n/(n+6.5)·(actual − prior)`, where the prior is the ECR-calibrated projection from `board-inputs.csv` (left unchanged). `k = 6.5` was fit on Sleeper 2025-26 logs with each player's 2024-25 FP/g as a stand-in prior (≥10 GP, ≥20 FP/g, 209–222 players), predicting rest-of-season FP/g after `n = 3, 5, 10, 20`. Pooled RMSE was 5.82, against 7.43 for the prior alone and 7.74 for actual results alone. The best k for each n ranged from 6.0 to 7.5. On 2024-25, the out-of-sample season, RMSE was 5.22 at this k and 5.19 at that season's own best k (9.0). Blending minutes and FP per minute separately improved RMSE by less than 1%, so one k is used. A real projection is probably a better prior than last season's FP/g, so this k may lean slightly toward actual results. `--blend --write` saves the per-player actuals snapshot in `board-actuals.csv`, and plain `--write`/`--test` rebuild from it offline. With zero games played, the board is identical to the frozen one. The replacement baseline uses blended FP/g, and expert-gap reviews still use the frozen-projection rank. GP and cluster inputs are not changed automatically, because early missed games are a noisy availability signal. Edit them with a source when an injury justifies it. **IN-SEASON ADD** rows are non-board players with an NBA team, at least 3 games, and both actual and blended FP/g above replacement. Their prior is last season's FP/g if they played at least 10 games (k 6.5); otherwise it is a league mean of 28.4 FP/g with k 2.5, fit on players who kept playing and therefore optimistic for fringe players. Adds use 74 GP, the board median. Preview a past season, without writing, with `--blend --season 2025 --through-week 4`.
- **Sensitivity checks (`P4.3`):** all top ten remain top ten with fully dispersed versus fully clustered absences and with the expert adjustment removed. Because `FantasyPros_2026_Draft_ALL_Rankings.csv` does not specify whether expert ranks represent full-season totals or per-game value (and our `board-inputs.csv` contains manual Oct 19 GP cuts not known to static rankers), we keep the bounded per-game ECR curve unchanged and record all top-140 rank moves of 5 or more places under the alternative season-space conversion (`sort((ppg − espn_delta) · gp)` divided by `gp`):

| Player | GP | ECR | Current rank | Season-space ECR rank | Rank delta | Calibrated FP/g delta |
|---|---:|---:|---:|---:|---:|---:|
| LeBron James | 61 | 28 | 32 | 27 | +5 | +0.65 |
| Kawhi Leonard | 60 | 35 | 35 | 25 | +10 | +1.74 |
| Donovan Clingan | 76 | 61 | 81 | 86 | -5 | -0.32 |
| Brandon Ingram | 55 | 75 | 87 | 82 | +5 | +0.72 |
| Brandin Podziemski | 79 | 100 | 101 | 106 | -5 | -0.58 |
| Kristaps Porziņģis | 50 | 118 | 127 | 122 | +5 | +0.37 |

Saved injury sources, October 19 snapshot:

These sources informed the frozen inputs. They are not a fresh clearance for draft night. Check the publication date and latest news before relying on a player's recovery or return timeline.

- Tatum returned in March; active recovery risk, not a season-long exclusion: https://www.nba.com/celtics/news/sidebar-post-20260306-jayson-tatums-return-sparks-celtics-in-20-point-rout-of-mavs
- Haliburton played preseason in October: https://www.nba.com/pacers/news/preview-pacers-bucks-261016
- Kyrie returned October 11: https://www.nba.com/news/kyrie-irving-makes-return-in-nba-china-game
- Embiid played October 16; absence risk remains: https://www.nba.com/player/203954/joel-embiid
- Ingram's debut delayed after heel surgery/partial Achilles tear; no confirmed return date: https://cdn-uat.nba.com/news/brandon-ingrams-clippers-debut-on-hold-after-heel-surgery-partial-achilles-tear
- Claxton faces another approximate two weeks after the October 19 re-evaluation. Keep 66 GP rather than deducting the same initial absence twice: https://www.fantasypros.com/nba/news/614790/nic-claxton-hamstring-to-be-re-evaluated-two-weeks.php
- Bam practiced October 19; opener not confirmed: https://www.rotowire.com/basketball/headlines/bam-adebayo-injury-takes-part-in-practice-monday-535188
- Curry ankle reassurance from Kerr, not a formal clearance: https://cdn-uat.nba.com/news/steve-kerr-stephen-curry-fine-after-tweaking-right-ankle-at-warriors-practice
- Franz remains questionable with a shoulder injury: https://cdn-uat.nba.com/news/nba-fantasy-week-1-yahoo-high-score-heroes
- Sabonis returned for 30 preseason minutes October 16: https://www.nba.com/player/1627734/domantas-sabonis

## Original projection construction

- **Projections:** FantasyPros 2026-27 season projections (totals incl. GP), 264 players — https://www.fantasypros.com/nba/projections/overall.php. Raw conversion kept in `board-fantasypros.txt`.
- **Shot attempts:** FantasyPros gives percentages only. FGA solved from PTS = 2·FGM + 3PM + FTM with each player's 2025-26 FTA/FGA from Basketball-Reference (0.25 if none) — https://www.basketball-reference.com/leagues/NBA_2026_per_game.html
- **Scoring:** pts 1, reb 1.5, ast 2, stl 2.5, blk 2.5, TO −2, FGM +2, FGA −1, FTM +1, FT miss −1, 3PM +1. Season totals are retained as source/reference, not the current ranking objective.
- **Oct 19 corrections** (`reports/2026-10-19/news-sweep.md`, `board-audit.md`): GP cut for Kawhi 60 (load mgmt), LeBron 61 (rest b2bs), Ingram 55 (Achilles), Morant 65 and −5%/g (bench role), Knueppel 72, Coby White 66, Claxton 66, Dejounte Murray 66, Hart 71, Dybantsa 72, Tobias Harris 72, Porziņģis 50; re-sorted. Team/position text dropped from notes (draft.py prints Sleeper's). Sochan removed (no team). 10 unprojected Sleeper top-200 players appended at the bottom.
- **Oct 19 return-from-injury haircut (evening):** FantasyPros had Haliburton at roughly his pre-injury level in this scoring. NBA players' first season after an Achilles rupture averaged 83% of pre-injury minutes and 80% of PER (n=27, https://scholarlycommons.henryford.com/orthopaedics_articles/308). Both Haliburton and Lillard report no restrictions, so we apply about half that effect: Haliburton −10%/g, 65 GP, c 0.65; Lillard (36) −10%/g, 62 GP, c 0.65; Tatum (2nd season back) −5%/g, 72 GP; Kyrie (post-ACL) −5%/g, 65 GP. Judgment inputs in `board-inputs.csv`. New ranks: Tatum 6→9, Haliburton 19→42, Kyrie 38→43, Lillard 44→67.

## Final expert-discrepancy review, October 19 evening

`python3 rebuild_board.py --audit` lists every gap of at least 20 places when either our rank or ECR is top 140. All 35 current gaps have an explicit `ecr_review` in the input CSV. `--write` refuses unexplained gaps, and `--test` also checks review coverage and saved-board equality. The review is a judgment record, not proof that a projection is correct. Current expert ranks were checked against FantasyPros' embedded 2026 Draft - Points data on October 19 and matched the imported export. Every expert top-140 name is covered; the ten unprojected players have no imported ECR better than 181.

Additional input corrections:

- VanVleet: 73 to 65 GP and 32.53 to 30.91 FP/g. This applies the same conservative 5% production adjustment used for Kyrie. The ACL return and possible workload limit justify a discount; its size is judgment. Source: https://www.nba.com/player/1627832/fred-vanvleet
- Lively: 72 to 55 GP and clustered-miss share 0.65. His foot return remains unconfirmed. The 55-game assumption is a conservative scenario, not a reported return date. His healthy production estimate stays intact. Source: https://www.nba.com/player/1641726/dereck-lively-ii
- Kevin Porter Jr.: excluded after the October 19 waiver. Keep his original projection record for later re-evaluation, but remove him from replacement/calibration curves and all live recommendations even if Sleeper still reports a team. Source: https://sports.yahoo.com/nba/teams/milwaukee/transactions/
- Proportional production cuts now scale `espn_delta` by the same factor as `ppg`, so the custom-scoring premium describes the adjusted stat line.

Rookie discrepancies remain deliberate but uncertain projection bets. Boozer #53/ECR105, Wilson #54/109, Dybantsa #63/129 and Acuff #72/122 derive mainly from source production assumptions, not Lock-In or custom-scoring advantages. A hypothetical 10% production cut moves them roughly to #80-98 and removes about four weekly surplus points. This sensitivity is not evidence for a blanket 10% penalty. Team previews support major roles for Boozer, Wilson and Acuff; retain their projections and expose the risk in the live board. Peterson and Wagler also carry rookie-risk reviews. Brown's restriction and bench role are explicit warnings; its unknown duration cannot justify a precise season haircut.

Role evidence: [Memphis](https://www.nba.com/news/2026-27-season-preview-mem), [Chicago](https://www.nba.com/news/2026-27-season-preview-chi), [Sacramento](https://www.nba.com/news/2026-27-season-preview-sac), [Clippers](https://www.nba.com/news/2026-27-season-preview-lac), [Brown's restriction](https://sports.yahoo.com/articles/mikel-brown-won-t-start-024749326.html).

The audit checks pessimistic discrepancies too. Buzelis, Clingan, Sarr, Alexander-Walker, Rollins, Mathurin and Sheppard have source production or minutes below what their expert ranks imply. Their reviews flag upside for comparison within tiers. Edey's high last-season average came from only 11 games; his conservative source minutes do not justify an automatic boost. No verified broad scoring error emerged: sampled exact FantasyPros shooting projections differ from the saved conversion by less than 0.5 FP/g. Generic ECR is a check on assumptions, not a replacement objective.

## Status (start of season, Oct 20)

The draft is complete and the in-season GM is on `main`. A new session starts from [`CLAUDE.md`](CLAUDE.md) (the GM charter), runs the `/daily`, `/week` and `/recap` briefs, and takes new work from the [open GitHub issues](https://github.com/allmanr/fb-gm/issues). Links to `allmanr/fb-gm-private` are the private pre-split repository, where issues and PRs #1–#32 and their review threads live; its open issues moved here as #2–#6; this section keeps only the current state.

**Done**
- **Draft** ([PR #1](https://github.com/allmanr/fb-gm-private/pull/1)–[#4](https://github.com/allmanr/fb-gm-private/pull/4)): weekly Lock-In board and live draft assistant, then 140/140 picks. The outcome, all rosters and projected standings are in the private draft retrospective (`private/reports/2026-10-19/draft-retro.md`).
- **In-season GM** ([PR #6](https://github.com/allmanr/fb-gm-private/pull/6)): `gm.py`, `trade.py`, the in-season board blend (`rebuild_board.py --blend`), the `scout` and `league-watcher` specialists, the briefs, and the GM notes (now `private/notes/`). The lock math, bench factor and playoff weighting are tested in [the backtest](reports/2026-10-20/lockin-backtest.md) (reproducible from a fresh clone) and [the playoff schedules](reports/2026-10-20/playoff-schedule.md). The build history and environment audit are in the private session retrospective (`private/reports/2026-10-20/session-retro.md`).
- **Lock records** ([PR #13](https://github.com/allmanr/fb-gm-private/pull/13)): `./gm.py lock "<player>" <score> --commit` records a Sleeper lock once per week, and `week`, `lock`, `fa` and `matchup` apply it (issue #8, part 1).
- **Housekeeping (Oct 20):** removed the four feature worktrees, deleted the merged branches, moved unrelated research out of the repo, and made `gm.py` use one scoring table.
- **Opening-day build (Oct 20, [PR #14](https://github.com/allmanr/fb-gm-private/pull/14)–[#18](https://github.com/allmanr/fb-gm-private/pull/18)):**
  - CI runs `scripts/check.sh` on Python 3.8 for every push and PR.
  - `trade.py` prints a simulated-rotation value next to the flat bench factor (#10; random rosters 0.613, ours 0.430).
  - The official NBA injury report sets play chances for the games it lists, and `fa` has a backtested minutes radar (#11).
  - Deadlines print in CT at the slot's next tip, and no feeds are planned after a tip (#8 part 3).
  - Seven fixes from a live smoke test: `week` lists every slot move and agrees with `lock`; player tags refetch after 3 h; GTD is treated as DTD; `trade.py` prints ERROR for typos and validates the league; drop labels; the matchup header label; the last-day note.
- **Same-night slot reuse** ([#22](https://github.com/allmanr/fb-gm-private/issues/22), [PR #23](https://github.com/allmanr/fb-gm-private/pull/23)): on nights with tips 3 h+ apart, `week` gives an idle bench player a slot before or after its early game, and the early score's deadline moves to the late tip. An earlier score's lock line and deadline also count a later night's swap, so an early swap into his slot sets the deadline. The backtest gives +0.60 wins per 20 weeks ([report](reports/2026-10-20/slot-reuse.md)). The model expects only a quarter of the gain real scores showed; that gap goes to #12.
- **Execution review** ([#21](https://github.com/allmanr/fb-gm-private/issues/21), [PR #25](https://github.com/allmanr/fb-gm-private/pull/25)): `./gm.py review [--week N]` prints, for each slot of a finished week, the points counted (lock record, else Sleeper's slot points), the lock policy replayed on the same box scores and the hindsight best. It names each leak's cause: a lock below the line, no lock recorded, a DNP final, a 0–1 game slot, or planned feeds (adherence unknown). A slot with an unprojected player prints policy n/a and stays out of the totals. `/recap` uses it and logs its outcome line. The policy uses this session's roster and board with everyone healthy and no same-night reuse. First real run: Mon Oct 26.
- **Pooled bench locks** ([#26](https://github.com/allmanr/fb-gm-private/issues/26), [PR #27](https://github.com/allmanr/fb-gm-private/pull/27)): `week`'s rotation plan seats every bench player who plays and fits an idle starter's slot. A bench score can then be locked "via" a cheaper idle slot: lock him in place, move his slot's next player there, and bench that slot's starter. `lock` decides the same night's bench scores jointly: the best score takes the cheapest line it reaches, and a via lock must clear its line by 1 FP for the extra move. `week` prints the via lines. The 2025-26 backtest gives +4.2 FP/wk and +0.80 wins/20 wk ([report](reports/2026-10-21/pooled-locks.md), [PR #28](https://github.com/allmanr/fb-gm-private/pull/28)). `review` replays the same pooled policy (the backtest's pooled arm, matched on 150 of 150 real team-weeks), pairs each slot by player and judges a via lock on its via line (PR #30).
- **Matchup lines** (Oct 22, Owner request; reopens [#9](https://github.com/allmanr/fb-gm-private/issues/9), which closed at +0.24 wins/season, 95% CI +0.18 to +0.30, below the 0.3 gate): in the live week, `lock` (single and pending, joint bench calls included) and `week` replace each slot's EV wait value with the score at which locking maximizes P(win H2H) + P(beat median). Our slots, the opponent and the other teams are each normal (mean, variance). Recorded locks are exact. Other unrecorded slots use Sleeper's reported points with `team_score`'s rule. The median term is exact under that model, as in the [backtest](reports/2026-10-20/winodds-locks.md). `lock --commit` now also records other teams' locks; the Owner reads them off Sleeper's matchup view, since the API has no lock flag. Each record stores the roster that locked it and the slot (`[score, roster_id, slot]`; a bare score reads as ours). A player who changes teams carries no lock to his new team, and his old team keeps the score in that slot. Once a slot's game today is probably final (tip + 3 h), its state uses the reported score with the value of waiting from tomorrow. This also fixes `matchup`'s odds, which counted a phantom roll tonight; a game in progress still counts as to come. Review dispositions are in [PR #8](https://github.com/allmanr/fb-gm/pull/8). Within 0.002 expected wins of indifferent, the EV line decides, so a decided week keeps its points. Shifts are under 1 FP early in a week and 3–4 FP late in a close one. Caveats: the backtest's gain assumed every state known, and the win model is overconfident (#5), so the live gain is below +0.24. `review` still replays the EV policy. `--ev` restores EV lines.
- **Late-season availability** ([#6](https://github.com/allmanr/fb-gm/issues/6)): fantasy-relevant players on the 10 worst teams at the deadline keep 0.71 of their usual weeks in the playoff window (95% CI 0.57–0.84), against 0.92 on other teams, pooled over 2024-25 and 2025-26 ([report](reports/2026-10-21/late-season.md)). `trade.py`'s playoff weighting (`po_mult`, `--suggest --playoff`, the simulated PO column) multiplies the schedule factor by the live group's factor, once every team has played 15 games, with the group mean before that. Treat it as an upper bound: the May 2026 lottery reform may shrink it.

**Open (impact → where tracked)**
- **Fri Oct 23 morning:** recheck whether Sleeper's matchup points show the locked score or the latest game; the Oct 21 check found live scores under our scoring but no player with two games yet ([sleeper-rules](reports/2026-10-20/sleeper-rules.md)). This decides automatic lock detection and how far in-week win odds can be trusted → [#3](https://github.com/allmanr/fb-gm/issues/3).
- **Confirm in the app** the waiver type, trade-deadline date and veto setting. These set the timing of waiver and trade advice → [#3](https://github.com/allmanr/fb-gm/issues/3).
- **Lock auto-detection** (#4 part 2) waits on the Friday recheck → [#4](https://github.com/allmanr/fb-gm/issues/4).
- **Calibrate heuristics after week 4:** win odds, trade acceptance, the stream rule, DNP rates and the blend's k → [#5](https://github.com/allmanr/fb-gm/issues/5).
- **Roadmap:** opt-in scheduled lineup rotations [#2](https://github.com/allmanr/fb-gm/issues/2) need the Owner's approval for account writes. Optional items in #3: scheduled briefs (needs an Owner-chosen push channel) and the DNP/gp overlap (small, uniform bias; measure only if #5 flags DNP rates).
- **Watch:** the `trade.py` simulation drives `--suggest` ranking, but acceptance still uses the flat view. Compare the flat and simulated deltas on real offers before trusting the simulation alone.
- **Accepted limits:** schedule, box-score, ESPN tip and NBA injury-report sources are undocumented or unofficial feeds, and each degrades with a NOTE; injury-report players are matched by name only; same-night slot reuse plans at most one extra roll per slot a night and assumes the early game ends within 3 h of its tip; a mid-week NBA trade makes `lock` refuse for that player rather than guess; recommendations-log entries are dated hypotheses, so recompute them from the live lineup before repeating them; E, `matchup`, `fa` ΔTeam and `trade.py` value each slot alone, without pooled bench locks (worth +4.2 FP/wk for a typical team, which every team's model leaves out alike, so win odds barely move; one player's share is about 1 FP/wk or less, under the 5 FP stream bar; #26).

**Closed — reopen only for new evidence**
- **Per-game context means** ([#32](https://github.com/allmanr/fb-gm-private/issues/32)): opponent and teammates-out adjustments to lock lines were backtested at +0.04 wins/20 wk (95% CI −0.20 to +0.29), even with absences known in advance, which is below the 0.3 gate. The effects are real (fit on 2024-25, R² 0.025 out of sample) but too small to flip lock calls. Back-to-back second nights have no scoring effect ([report](reports/2026-10-21/context-means.md)).
- **PR #25 review findings** (Codex's three P2s and the local review), fixed in `2d4d7a8` with tests that fail without each fix: Sunday-night `review` (the week counts as finished once every game that day tipped 3 h ago), policy `n/a` for unprojected slots, and a repeated score judged at its latest game. Dispositions are in the [PR #25 thread](https://github.com/allmanr/fb-gm-private/pull/25). Accepted: when one score repeats, an early lock below its line can go unflagged.
- **PR #23 review findings** (Codex and the local review): two lock-path fixes, each with a test that fails without it (`f1c2cbf`). The first counts later nights' reuse rolls in a lock's continuation and deadline. The second keeps a same-night DTD replacement's 0.50 play chance. Dispositions are in the [PR #23 thread](https://github.com/allmanr/fb-gm-private/pull/23). Opponents' modeled same-night reuse in `matchup` was left as is: it's worth about 0.5–0.8 FP/wk, too little to move the win odds.
- **PR #6 review findings** (Codex, the local review and two final reviews, about 25 in all) are fixed, each with a regression test that fails without the fix. Dispositions are in the [PR #6 thread](https://github.com/allmanr/fb-gm-private/pull/6). Notable decisions:
  - Trade values are season-horizon, so IR slots change only the roster count, never value (`a6cbac7`).
  - Lock calls judge the slot, not the player alone.
  - A free agent whose team has tipped this week is a waiver claim, not a stream.
- **Model history:**
  - Draft-night refresh workflows are done.
  - The season-total objective and old simulations were superseded by the one-game-per-week format, and the flat-CV approximation by the fitted Lock-In model.
  - Hindsight replacement bias is fixed by matched-schedule replacement.
  - Season-space ECR conversion is deferred pending source semantics; unsupported injury-cluster changes were withdrawn.
  - The generic Sleeper-projection board was replaced by custom scoring. Traded-pick math is immaterial (pick trading is off), and raw-versus-live-board drift is intentional.
