#!/usr/bin/env bash
# Start token-watch (a script, no model) in tmux session "token-watch". Stop it with: tmux kill-session -t token-watch
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
if tmux has-session -t =token-watch 2>/dev/null; then echo "token-watch is already running"; exit 0; fi
tmux new-session -d -s token-watch -c "$D" "bash '$D/watch.sh'"
echo "token-watch started"
