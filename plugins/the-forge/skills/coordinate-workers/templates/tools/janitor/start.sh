#!/usr/bin/env bash
# Start the janitor (a script, no model): janitor.py --once every 10 minutes in tmux session "janitor".
# The rules are in janitor.py's docstring. Reports go to state/report.log next to it; the coordinator
# keeps `python3 -I <this folder>/janitor.py --wait` running in the background to hear about them.
# Try it first with: python3 -I janitor.py --once --dry-run
# Stop it with: tmux kill-session -t janitor
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="${WORKSPACE:-$(cd "$D/../../.." && pwd)}"
[[ -d "$WORKSPACE/.worktrees" ]] || { echo "STOP: no $WORKSPACE/.worktrees; set WORKSPACE to the workspace root" >&2; exit 1; }
command -v glab >/dev/null || { echo "STOP: glab is not on PATH" >&2; exit 1; }
if tmux has-session -t =janitor 2>/dev/null; then echo "janitor is already running"; exit 0; fi
tmux new-session -d -s janitor -c "$WORKSPACE" -e "WORKSPACE=$WORKSPACE" \
  "while true; do python3 -I '$D/janitor.py' --once; sleep 600; done"
echo "janitor started (tmux attach -t janitor to look)"
