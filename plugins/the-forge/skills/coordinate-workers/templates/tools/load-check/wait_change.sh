#!/usr/bin/env bash
# For the coordinator, run in the background: blocks until load-watch's verdict changes, then prints the
# new state and exits, which wakes the coordinator. Re-arm it after each change.
D="$(cd "$(dirname "$0")" && pwd)"
start=$(head -1 "$D/state" 2>/dev/null | cut -d' ' -f1)
while true; do
  sleep 30
  now=$(head -1 "$D/state" 2>/dev/null | cut -d' ' -f1)
  if [[ -n "$now" && "$now" != "$start" ]]; then echo "load: $start -> $now"; head -4 "$D/state"; exit 0; fi
done
