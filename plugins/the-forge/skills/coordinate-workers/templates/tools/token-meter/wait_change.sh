#!/usr/bin/env bash
# For the coordinator, run in the background: blocks until the token budget's verdict changes, prints the
# new line from state/events.log and exits, which wakes the coordinator. Re-arm it after each change.
D="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$D/state"; LOG="$D/state/events.log"; touch "$LOG"
n=$(wc -l < "$LOG")
while sleep 60; do
  m=$(wc -l < "$LOG")
  if (( m > n )); then sed -n "$((n + 1)),${m}p" "$LOG"; exit 0; fi
done
