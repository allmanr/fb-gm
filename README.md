# Basketball GM — Sleeper Lock-In & roster assistant

An agent-run front office for one team in a 10-team Sleeper NBA **Lock-In** redraft league (drafted October 19, 2026). It reads Sleeper and a weekly Lock-In value board and recommends lineups, rotations, locks, waivers and trades; the Owner makes every move in Sleeper. Keep Sleeper open to manage your lineup, and keep an agent chat open in this project for advice.

## Setup

Python 3.8+ (stdlib only; `pypdf` for the NBA injury report). Then:

```sh
mkdir -p private && cp config.example.json private/config.json   # your Sleeper league_id and user_id
./gm.py roster                                                    # validates the league, or prints REFUSING
```

The tools assume this league's scoring, slots and IR rules (see [CLAUDE.md](CLAUDE.md)); `gm.py` refuses a league whose settings differ. Install the pre-commit check once per clone with the line at the top of `scripts/check.sh`.

## Your roster

Run `./gm.py roster` for the live lineup, tags, board value and this week's games. The roster at draft close, every team's picks and the projected standings are in the private draft retrospective (`private/reports/2026-10-19/draft-retro.md`).

## Weekly Lock-In & roster management

In Sleeper Lock-In mode, each starting slot counts **one locked game score per week**:

- **Start before tip-off to earn a roll:** A player must be in a starting slot when their NBA game begins for that game's score to be eligible to lock.
- **Rotate bench players through unlocked slots:** Before locking a slot for the week, move bench players with early-week games into compatible starting slots (`PG/SG/G/SF/PF/F/C/UTIL`). If they boom, lock the score; if not, swap your next starter back in before their game starts.
- **Lock before the slot's next tip:** You must lock a finished game before that player's next NBA game tips off, and before you move anyone else into his slot (a benched player's score can't be locked). Locks are irreversible. `gm.py` prints each deadline in CT from ESPN's tip times. If you never lock a slot, Sleeper counts the starter's final game of the week (which is `0` if they sit).
- **IR rule:** Your 2 IR slots accept only Sleeper status `IR`, `Sus`, or `DNR` (`reserve_allow_out` is `0`). An `Out` player uses a bench spot.

## In-season workflow

Open an agent chat in this folder. In Claude Code the briefs are slash commands; other agents (Codex, agy) can be told to "follow `.claude/commands/daily.md`". Every `gm.py` command checks the live league first and prints `REFUSING` if scoring, slots, IR rules or roster ownership changed.

| When | Run | You get |
|---|---|---|
| Monday morning, before the first tip | `/week` | Game counts, base lineup, day-by-day bench rotation plan with its expected gain, waiver claims with drops, up to 2 trade ideas with opening offer and walk-away |
| Each game day, before the first tip (and late at night after games) | `/daily` | Under 15 lines: locks to make now with thresholds, who must be in a starting slot before today's tips, fixes (Out on bench, IR, empty slot) |
| After a game, deciding a lock | `./gm.py lock "<player>" <score> [--slot-of "<starter>"]` | LOCK or WAIT for the slot he occupies (its starter and planned feeders refill it if unlocked), his own wait value, and the threshold table |
| Monday, after Sunday's games | `/recap <week>` | Result incl. median game, locks reviewed, standings, manager notes, recommendation outcomes |
| Evaluating a trade offer or looking for one | `./trade.py "<give>" "<get>"`, `./trade.py --suggest` | Both teams' lineup-fit change in V/wk, forced drops, a simulated-rotation check of our bench fit, and whether they'd likely accept (judged by Sleeper rank, how this room drafted) |
| Monday, from week 2 on (`/week` does it) | `python3 rebuild_board.py --blend --write` | Board re-ranked with actual 2026 results blended into the projections; breakout free agents appear as `IN-SEASON ADD` |
| Anytime | `./gm.py roster`, `week`, `fa`, `matchup`, `standings`, `changes` | Live facts; see `./gm.py --help` |

After you lock a score in Sleeper, record it once: `./gm.py lock "Jarrett Allen" 52 --commit`. From then on `week`, `lock`, `fa` and `matchup` treat his slot as locked at 52 for the rest of the week: no feeds into it, no dropping him, and his 52 counts in the win odds. `./gm.py lock "Jarrett Allen" --uncommit` undoes a mistake. Records reset each week. `--locked "Name,Name"` still overrides them for a one-off what-if. The tools can't see locks in Sleeper, so record each one.

Record the opponent's locks the same way, with the score Sleeper's matchup view shows: `./gm.py lock "<their player>" 48 --commit` (an Owner player's name wins a tie). In the live week, `lock` and `week` set each slot's line to the score at which locking maximizes P(win H2H) + P(beat median), given every team's current state ([backtest](reports/2026-10-20/winodds-locks.md)). The more of the opponent's locks you record, the sharper that state is. As a favourite the lines drop (bank a safe score); as an underdog they rise (wait for upside). The effect is mostly late in a close week, and a decided matchup keeps the EV line. `--ev` prints the plain EV lines.

Play chances come from the official NBA injury report for the games it lists (Probable 75%, Questionable 50%, Doubtful 25%, Out 0) and otherwise from Sleeper's tag: DTD or GTD is 50% for the next game and 75% for later games, Out is 0 all week. `gm.py` says which source it used. Use current injury news and `lock --play P` when those assumptions do not fit.

Lock calls consider returning bench players even when the current starter is a rotated-in feeder and both play on the same date. `--play` and `--remaining` change only the named player's future rolls, not the other slot options. With a schedule, `--remaining N` keeps his last N upcoming game dates (skipping the earliest ruled-out games).

The GM keeps notes in `private/notes/` (recommendations log and manager profiles) and calls two specialists in `.claude/agents/`: `scout` (injury and rest news) and `league-watcher` (opponents and trade partners).

Ask in chat when managing your week:

- "Check this week's schedule and recommend my daily starter rotations and lock thresholds."
- "Should I lock this score or wait for their remaining games this week?"
- "Check the live rosters and top available free agents on our board. Is anyone worth dropping my weakest bench player for?"
- "Compare a trade offer using our weekly Lock-In values."

## View the board and completed draft

For the drafted roster and best undrafted players on `board.txt`, run:

```sh
./draft.py
```

Useful flags:

- `./draft.py --pos C` (or `PG`, `SG`, `SF`, `PF`, `G`, `F`) to filter available players by Sleeper eligibility.
- `./draft.py --top 40` to view deeper free-agent options.
- `./draft.py --refresh` to force a fresh download of `/players/nba` injury/team metadata.

Note: `./draft.py` reads the completed draft picks (`/draft/<draft_id>/picks`), not the live roster. For the live roster and free agents after waiver claims or trades, use `./gm.py roster` and `./gm.py fa`.

## Read the board without studying the numbers

- **B1** is the first remaining undrafted player on our board.
- **T1, T2, T3** are groups of similar estimated weekly value (`~2.0 V/wk` per tier). Lower tier numbers come first.
- **V+…/wk** estimates weekly Lock-In surplus above a matched-schedule healthy replacement player (`~26.9 FP/g`). Higher is better.
- **NO PROJECTION** means we do not have a points estimate for that player.

`ECR review: RISK` flags an uncertain projection behind a large expert-ranking disagreement. Prefer a proven peer within the same tier. `Board exclusions` lists players withheld from recommendations, including waived players whose Sleeper metadata may still show a team.

## Find the current notes

- [Project notes](prep-notes.md#league-rules): Lock-In rules and model documentation; [current status](prep-notes.md#status-start-of-season-oct-20) with what's open and where it's tracked.
- [GM charter](CLAUDE.md): league rules, ground rules, tools, staff and notes rules for the agent.
- [Lock-In backtest](reports/2026-10-20/lockin-backtest.md): lock thresholds, DNP correction and bench value tested on 2025-26 games. [Win-odds lock backtest](reports/2026-10-20/winodds-locks.md): +0.24 wins/season, below the build gate (#9). [Playoff schedules](reports/2026-10-20/playoff-schedule.md), [Sleeper rules check](reports/2026-10-20/sleeper-rules.md) [pooled bench locks](reports/2026-10-21/pooled-locks.md), [late-season availability](reports/2026-10-21/late-season.md) (playoff trade weighting) and [per-game context means](reports/2026-10-21/context-means.md) (closed #32).
- [Open work](https://github.com/allmanr/fb-gm/issues): GitHub issues, each with impact and acceptance criteria. Issue and PR numbers up to #32 in older notes, reports and code comments refer to the private pre-split repository (allmanr/fb-gm-private); its open issues moved here as #2–#6 (#7 → #3, #8 → #4, #12 → #5, #5 → #2, #31 → #6).
- [Research archive](reports/README.md): the board's pre-draft provenance.

## Private data

This repository is public. Everything that identifies the league or its people, or reveals strategy, lives in `private/`: a gitignored directory that is its own git repository (a private GitHub repo), cloned into place:

```sh
git clone git@github.com:<you>/<private-repo>.git private
```

| Path | Holds |
|---|---|
| `private/config.json` | League and Sleeper user IDs |
| `private/notes/` | Recommendations log and manager profiles |
| `private/draft-night.md`, `private/reports/` | Draft result and retrospective, scouting, cheat sheets, week scouts, playoff trade targets, the FantasyPros source export |
| `private/state/` | `gm.py changes` snapshot and `lock --commit` records (written by `gm.py`) |
| `private/needles.txt` | League name, IDs, usernames and team names that `scripts/check.sh` refuses in public commits |

Back up after a session that changed it: `git -C private add -A && git -C private commit -m notes && git -C private push`. The tools and their tests run without `private/` except for live league commands, which need `config.json`.
