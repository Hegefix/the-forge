#!/usr/bin/env bash
# The scribe's loop: every interval_min (config.json), any time of day, pass.py checks the gate (new
# decision-log lines or inbox notes). No news = one "no news" line in runs.log and no model. Otherwise ONE
# headless `claude -p` pass with an empty context. start-headless.sh runs this in tmux `scribe`. Passes never
# overlap: they run one after another here, and pass.py holds a lock.
set -uo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
export STATE_DIR="${STATE_DIR:-$D/state}"

echo "scribe loop started $(date '+%F %T'), state: $STATE_DIR"
while true; do
  python3 -I "$D/pass.py" || true
  every=$(python3 -I "$D/pass.py" --interval) || every=1200
  sleep "$every"
done
