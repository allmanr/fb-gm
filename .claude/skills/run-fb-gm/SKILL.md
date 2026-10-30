---
name: run-fb-gm
description: Run, test, and smoke-check the fb-gm Sleeper Lock-In tools (gm.py, trade.py, draft.py, rebuild_board.py). Use when asked to run gm.py, run the checks or tests, verify a gm.py/trade.py change against the live league, or call the lock math directly.
---

fb-gm is a set of stdlib Python CLIs that read the live Sleeper league and print advice. The handle is
`.claude/skills/run-fb-gm/smoke.sh`: offline suites, a direct lock-math call, then every read-only live
command as a `--date` dry run. Paths are relative to the repo root.

## Prerequisites

`/usr/bin/python3` 3.8 with `pypdf` (the scripts' shebang Python; CI pins 3.8 too). Check:

```bash
/usr/bin/python3 --version                                   # Python 3.8.10
/usr/bin/python3 -c "import pypdf; print(pypdf.__version__)" # 5.9.0
```

Live commands need `private/config.json` (league and user IDs). `private/` is gitignored and is its own
repo; without it, run only `smoke.sh offline`.

## Run (agent path)

```bash
.claude/skills/run-fb-gm/smoke.sh          # ~60 s: offline suites + direct calls + 10 live dry runs
.claude/skills/run-fb-gm/smoke.sh offline  # ~3 s: no network, no private/ needed
```

Each step prints `ok <name>` or `FAIL <name> (exit N): <file>`; a step fails on a non-zero exit or any
`REFUSING`/`Traceback` in its output. Full output lands in `/tmp/fb-gm-smoke/<name>.txt` (override with
`OUT=`). The script exits 1 if anything failed.

After changing a command, run it alone the same way and read the output:

```bash
./gm.py --date $(date +%F) week
./gm.py changes --no-write
```

### Direct invocation

Most PRs change one function in `gm.py` (lock windows, deadlines, matchup state). `import gm` has no side
effects and needs no config, so call the function directly:

```bash
/usr/bin/python3 -c "import gm; print([round(x, 1) for x in gm.thresholds(40)])"   # [36.8, 44.0, 47.9, 50.6, 52.6]
```

## Run (human path)

`./gm.py roster|week|lock|fa|matchup|standings|review` with no `--date`, or the `/daily`, `/week` and
`/recap` briefs. See `./gm.py --help`.

## Test

```bash
scripts/check.sh   # draft, rebuild_board, gm, trade --test; ~2.5 s, prints "ok" lines
```

The `gm.py --test` run prints `NOTE: win model drops latest scores ...` about nine times; that is expected.

## Gotchas

- **Live runs write private state.** Without `--date`, every command except `review` and
  `changes --no-write` records lineup observations in `private/state/lineups-<season>-w<week>.json`;
  `changes` without `--no-write` advances the snapshot; `lock ... --commit` records a lock. `smoke.sh`
  avoids all three; for poking around, use `--date $(date +%F)`.
- **`--date` changes the output.** It turns off the tip clock and matchup lines: `week` and `lock` print
  `NOTE: matchup lines unavailable ... lines below are EV wait values`. To check matchup-line code you need
  a real live run (which writes observations, above).
- **Global flags go before the subcommand.** `./gm.py roster --date X` fails with
  `unrecognized arguments: --date`; use `./gm.py --date X roster`.
- **Output is private league data.** Team names, usernames and rosters appear in every live command. Never
  paste it into public files; `scripts/check.sh` refuses staged text matching `private/needles.txt`.
- **Python 3.8.** No `zoneinfo`, `str.removeprefix` or `X | Y` types; `check.sh` runs on `/usr/bin/python3`
  so 3.9+ syntax fails there before CI.

## Troubleshooting

- **`FileNotFoundError: ... private/config.json`** (traceback from `load`): no private repo checked out.
  `cp config.example.json private/config.json` with real IDs, or run `smoke.sh offline`.
- **`gm.py: error: unrecognized arguments: --date`**: flag after the subcommand; move it before.
