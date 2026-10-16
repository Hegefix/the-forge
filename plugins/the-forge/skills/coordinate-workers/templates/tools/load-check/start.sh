#!/usr/bin/env bash
# Start load-watch (a script, no model) in tmux session "load-watch": load.sh every minute into ./state,
# verdict changes into ./events.log. Stop it with: tmux kill-session -t load-watch
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
if tmux has-session -t =load-watch 2>/dev/null; then echo "load-watch is already running"; exit 0; fi
tmux new-session -d -s load-watch -c "$D" "bash '$D/watch.sh'"
echo "load-watch started"
