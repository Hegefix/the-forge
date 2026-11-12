#!/usr/bin/env bash
# board-watch: checks every 60 s whether a scheduled time (config.json: `times`, `days`, `timezone`) has come and
# has not run yet; then runs ONE pass (pass.py --scheduled). No model runs between passes. A pass missed
# because the laptop slept still runs when it wakes, up to `grace_min` (3 h) after the time. start-headless.sh
# runs this in tmux `board-watch`.
set -uo pipefail
export PASS_STARTED_BY=loop
D="$(cd "$(dirname "$0")" && pwd)"
echo "board-watch loop started $(date '+%F %T'), state: ${STATE_DIR:-$D/state}"
while true; do
  python3 -I "$D/pass.py" --scheduled || true
  sleep 60
done
