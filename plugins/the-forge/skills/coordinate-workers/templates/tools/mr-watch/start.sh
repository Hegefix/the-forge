#!/usr/bin/env bash
# Start mr-watch (a script, no model) in tmux session "mr-watch": watch_mrs.py polls your open MRs, and the
# ones listed in mrs.txt, every 90 s, and appends one line per change to events.log. The coordinator keeps
# `python3 -I <this folder>/wait_event.py` running in the background to hear about them.
# Settings: see watch_mrs.py. Stop it with: tmux kill-session -t mr-watch
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
command -v glab >/dev/null || { echo "STOP: glab is not on PATH" >&2; exit 1; }
if tmux has-session -t =mr-watch 2>/dev/null; then echo "mr-watch is already running"; exit 0; fi
env_args=()
for v in MR_WATCH_AUTHOR MR_WATCH_IGNORE MR_WATCH_HOST MR_WATCH_INTERVAL; do
  [[ -n "${!v:-}" ]] && env_args+=(-e "$v=${!v}")
done
tmux new-session -d -s mr-watch -c "$D" ${env_args[@]+"${env_args[@]}"} \
  "python3 -I '$D/watch_mrs.py' >> '$D/events.log' 2>> '$D/errors.log'"
echo "mr-watch started (events in $D/events.log)"
