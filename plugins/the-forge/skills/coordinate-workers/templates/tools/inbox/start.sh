#!/usr/bin/env bash
# Start the inbox bridge (a script, no model) in tmux session "inbox". It turns the helpers' output and due
# timers into events in events.jsonl; the coordinator keeps one `python3 -I <this folder>/wait.py` armed.
# Check what it will read first: python3 -I bridge.py --check
# Stop it with: tmux kill-session -t inbox (restart with this script; it continues where it stopped)
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
python3 -I "$D/bridge.py" --check >/dev/null || exit 1
if tmux has-session -t =inbox 2>/dev/null; then echo "inbox bridge is already running"; exit 0; fi
mkdir -p "$D/state"
tmux new-session -d -s inbox -c "$D" "python3 -I '$D/bridge.py' 2>&1 | tee -a '$D/state/bridge.log'"
# wait.py exits 2 until the first pass has written a heartbeat: give it up to 20 s
for _ in $(seq 20); do python3 -I "$D/wait.py" --status >/dev/null 2>&1 && break; sleep 1; done
python3 -I "$D/wait.py" --status || { echo "STOP: no heartbeat yet; see $D/state/bridge.log" >&2; exit 1; }
echo "inbox bridge started (tmux attach -t inbox to look)"
