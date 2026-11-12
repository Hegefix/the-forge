#!/usr/bin/env bash
# Start board-watch: loop.sh in tmux session "board-watch". At the times in config.json it runs one headless
# `claude -p` pass that audits the board against the merge requests, and writes a digest file to state/digests/
# only when it has news. The coordinator's digest waiter covers that folder (see README.md).
# Try one pass first: python3 -I pass.py --once (with STATE_DIR=state-test to keep the real state clean).
# Stop it with: tmux kill-session -t board-watch
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "STOP: pass.py needs python3 3.9 or later" >&2; exit 1; }
# Claude Code ignores a settings file it can't parse, without an error, and then nothing is denied.
PROFILE=$(python3 -I - "$D" <<'PY'
import json, os, sys
d = sys.argv[1]
c = json.load(open(os.path.join(d, "config.json")))
w = os.environ.get("WORKSPACE")
while not w:
    d2 = os.path.dirname(d)
    if d2 == d: sys.exit("no workspace holds " + c["profile"])
    d = d2
    if os.path.exists(os.path.join(d, c["profile"])): w = d
p = os.path.join(w, c["profile"])
json.load(open(p))["permissions"]["deny"]
print(p)
PY
) || { echo "STOP: config.json or the watcher profile is missing or not valid JSON" >&2; exit 1; }
if grep -q -E '<[A-Za-z][^<>"]*>' "$PROFILE" "$D/config.json"; then echo "STOP: $PROFILE or config.json still has a <placeholder>" >&2; exit 1; fi
if tmux has-session -t =board-watch 2>/dev/null; then echo "board-watch is already running"; exit 0; fi
claude_bin=$(command -v claude) || { echo "STOP: claude is not on PATH" >&2; exit 1; }
tmux new-session -d -s board-watch -c "$D" \
  "$(printf '%q ' env "PATH=$PATH" "CLAUDE_BIN=$claude_bin" ${WORKSPACE:+"WORKSPACE=$WORKSPACE"} "$D/loop.sh")"
echo "board-watch started (tmux attach -t board-watch to look); digests in $D/state/digests/"
