#!/usr/bin/env bash
# Start the scribe: loop.sh in tmux session "scribe". Every interval_min a gate with no model checks the decision
# log and state/inbox/; only when one has something new does one headless `claude -p` pass run, and it keeps the
# notes (dashboard, the handover note's State, knowledge notes) current.
# Notes for the scribe: save.sh "<conclusion>". Its notices for the coordinator land in state/notices/; wait on
# them with the comms watcher's wait_digest.py (one waiter for both folders):
#   python3 -I coordination/tools/comms-watch/wait_digest.py coordination/tools/comms-watch/state/digests \
#     coordination/tools/scribe/state/notices
# Settings: config.json next to this file. Environment: WORKSPACE (default: the folder that holds
# coordination/tools/scribe/).
# Stop it with: tmux kill-session -t scribe
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="${WORKSPACE:-$(cd "$D/../../.." && pwd)}"
PROFILE="$WORKSPACE/coordination/permission-profiles/watcher.json"
[[ -d "$WORKSPACE/coordination" ]] || { echo "STOP: no $WORKSPACE/coordination; set WORKSPACE to the workspace root" >&2; exit 1; }
# Claude Code ignores a settings file it can't parse, without an error, and then nothing is denied.
python3 -c "import json,sys; json.load(open(sys.argv[1]))['permissions']['deny']" "$PROFILE" ||
  { echo "STOP: $PROFILE is missing or not valid JSON with a permissions.deny list" >&2; exit 1; }
if grep -q -E '<[A-Za-z][^<>"]*>' "$PROFILE"; then echo "STOP: $PROFILE still has a <placeholder>" >&2; exit 1; fi
python3 -c "import json,sys; json.load(open(sys.argv[1]))['notes']" "$D/config.json" ||
  { echo "STOP: $D/config.json is missing or not valid JSON with a notes block" >&2; exit 1; }
if grep -q -E '<[A-Za-z][^<>"]*>' "$D/config.json"; then echo "STOP: $D/config.json still has a <placeholder>" >&2; exit 1; fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "STOP: pass.py needs python3 3.9 or later" >&2; exit 1; }
if tmux has-session -t =scribe 2>/dev/null; then echo "scribe is already running"; exit 0; fi
# tmux runs the command with the tmux server's environment, whose PATH may differ from ours.
claude_bin=$(command -v claude) || { echo "STOP: claude is not on PATH" >&2; exit 1; }
tmux new-session -d -s scribe -c "$D" \
  "$(printf '%q ' env "PATH=$PATH" "CLAUDE_BIN=$claude_bin" "WORKSPACE=$WORKSPACE" "$D/loop.sh")"
echo "scribe started (tmux attach -t scribe to look); notices in $D/state/notices/"
