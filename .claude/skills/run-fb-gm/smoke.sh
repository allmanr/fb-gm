#!/bin/sh
# Smoke-drive fb-gm: offline suites, direct lock math, then every read-only live command as a --date dry run.
# --date keeps runs from writing private/state (lineup observations); fetches still hit Sleeper/ESPN/NBA live.
# Usage: .claude/skills/run-fb-gm/smoke.sh [offline]   (offline: skip the live commands)
set -u
cd "$(git rev-parse --show-toplevel)"
PY=${PY:-/usr/bin/python3}
OUT=${OUT:-/tmp/fb-gm-smoke}
mkdir -p "$OUT"
fail=0

run() {  # run <name> <cmd...>: exit 0 and no REFUSING/Traceback, output kept in $OUT/<name>.txt
  name=$1; shift
  "$@" > "$OUT/$name.txt" 2>&1; rc=$?
  if [ $rc -ne 0 ] || grep -qE 'REFUSING|Traceback' "$OUT/$name.txt"; then
    echo "FAIL $name (exit $rc): $OUT/$name.txt"; fail=1
  else
    echo "ok   $name ($(wc -l < "$OUT/$name.txt") lines)"
  fi
}

run check env PY="$PY" scripts/check.sh
# 40 FP/g lock lines with 1..5 games left, and one box score under league scoring (hand-computed 50.0).
run direct "$PY" -c "
import gm
assert [round(x, 1) for x in gm.thresholds(40)] == [36.8, 44.0, 47.9, 50.6, 52.6], gm.thresholds(40)
assert gm.game_fp({'pts': 20, 'reb': 10, 'ast': 5, 'stl': 1, 'blk': 1, 'fgm': 8, 'fga': 15, 'ftm': 4, 'fta': 5, 'to': 2}) == 50.0
print('ok')"

if [ "${1:-}" != offline ]; then
  [ -f private/config.json ] || { echo "FAIL live: no private/config.json (cp config.example.json private/config.json)"; exit 1; }
  T=$(date +%F)
  for c in roster week matchup lock fa standings review; do run "$c" "$PY" gm.py --date "$T" "$c"; done
  run changes "$PY" gm.py changes --no-write
  run trade "$PY" trade.py --suggest --top 3
  run draft "$PY" draft.py --top 5
fi
exit $fail
