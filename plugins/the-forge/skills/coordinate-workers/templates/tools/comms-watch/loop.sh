#!/usr/bin/env bash
# The comms watcher's loop: one headless `claude -p` pass (pass.py) per interval, each with an empty context.
# No model runs between passes. config.json's schedule picks the interval; start-headless.sh runs this in
# tmux `comms-watch`. Passes never overlap: they run one after another here, and pass.py holds a lock.
set -uo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
export STATE_DIR="${STATE_DIR:-$D/state}"

echo "comms-watch loop started $(date '+%F %T'), state: $STATE_DIR"
last=0
while true; do
  # The interval is checked every 30 s against the current time, so the start of a busier window (08:00 on a
  # workday) starts a pass at once instead of waiting out the night's interval. 0 = no passes right now.
  if every=$(python3 -I "$D/pass.py" --interval); then
    if (( every > 0 && $(date +%s) - last >= every )); then
      last=$(date +%s)
      python3 -I "$D/pass.py" || true
    fi
  else
    echo "$(date '+%F %T') config.json unreadable; retrying in 5 min"
    sleep 270
  fi
  sleep 30
done
