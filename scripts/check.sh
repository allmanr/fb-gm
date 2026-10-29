#!/bin/sh
# Offline checks for every commit. Runs on the machine's /usr/bin/python3 (3.8),
# which is what the script shebangs use, so 3.9+ syntax or stdlib fails here.
# Install once per clone (the hook is shared by all worktrees and runs each worktree's own copy):
#   printf '#!/bin/sh\nf="$(git rev-parse --show-toplevel)/scripts/check.sh"\n[ -x "$f" ] && exec "$f"\nexit 0\n' \
#     > "$(git rev-parse --git-common-dir)/hooks/pre-commit" && chmod +x "$(git rev-parse --git-common-dir)/hooks/pre-commit"
# Suites: gm.py (validation refusal, lock math, rotation, tip clock, injury report, FA and change
# diffs, execution review), trade.py (resolution, lineup deltas, uneven trades, suggest), draft.py
# (draft order, lineup fitting, display), rebuild_board.py (board model and saved board), and
# check_docs.py (links, anchors and script flags named in the agent docs).
# fit_lockin.py --test needs the network and is not run here; it fetches 2025-26 Sleeper logs to
# verify the fitted constants, including the blend's.
set -e
cd "$(git rev-parse --show-toplevel)"
PY=${PY:-/usr/bin/python3}  # CI sets PY to its 3.8
$PY draft.py --test
$PY rebuild_board.py --test
$PY gm.py --test
$PY trade.py --test
$PY scripts/check_docs.py
git diff --cached --check
# This repo is public: refuse staged text containing a private league identifier (absent in CI).
if [ -f private/needles.txt ] && git grep --cached -I -n -F -f private/needles.txt; then
  echo "REFUSING: private league identifiers above (private/needles.txt); move that text under private/" >&2
  exit 1
fi
