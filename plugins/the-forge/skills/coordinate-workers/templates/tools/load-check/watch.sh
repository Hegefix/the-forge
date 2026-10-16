#!/usr/bin/env bash
# load-watch: runs load.sh every 60 s. Writes the current output to state, appends a line to events.log
# whenever the verdict changes, and a snapshot every 10 minutes. Started by start.sh.
set -uo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
last=""; n=0
while true; do
  out="$("$D/load.sh" 2>&1)"
  first="${out%%$'\n'*}"; verdict="${first%% *}"
  printf '%s\n' "$out" > "$D/state"
  if [[ "$verdict" != "$last" ]]; then
    echo "$(date '+%H:%M') ${last:-START} -> $first" >> "$D/events.log"
    last="$verdict"
  elif (( n % 10 == 0 )); then
    echo "$(date '+%H:%M') snapshot $first" >> "$D/events.log"
  fi
  n=$((n + 1)); sleep 60
done
