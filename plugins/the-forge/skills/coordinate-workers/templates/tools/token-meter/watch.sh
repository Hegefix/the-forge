#!/usr/bin/env bash
# token-watch: every 10 minutes writes `meter.py gate` to state/last, the verdict to state/verdict, and each
# verdict change to state/events.log. No model runs. Started by start.sh.
D="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$D/state"
while true; do
  line=$(python3 -I "$D/meter.py" gate 2>/dev/null | tail -1)
  v=${line%% *}
  old=$(cat "$D/state/verdict" 2>/dev/null)
  printf '%s\n' "$line" > "$D/state/last"
  if [[ -n "$v" && "$v" != "$old" ]]; then
    printf '%s\n' "$v" > "$D/state/verdict"
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M')" "$line" >> "$D/state/events.log"
  fi
  sleep 600
done
