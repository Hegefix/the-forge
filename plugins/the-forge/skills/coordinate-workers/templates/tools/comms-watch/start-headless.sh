#!/usr/bin/env bash
# Start the comms watcher: loop.sh in tmux session "comms-watch", one headless `claude -p` pass per interval
# (config.json's schedule). Each pass reads what's new in chat, the tracker, the wiki, mail and the git hosting
# to-dos, and writes one digest file per pass with news to state/digests/. The coordinator waits for them, and for
# the scribe's notices (leave out that folder without a scribe), with one waiter:
#   python3 -I coordination/tools/comms-watch/wait_digest.py coordination/tools/comms-watch/state/digests \
#     coordination/tools/scribe/state/notices
# A pass runs with --permission-mode dontAsk, only the read tools listed in config.json, and the watcher
# profile's deny rules on top.
# Settings: config.json next to this file. Environment: WORKSPACE (default: the folder that holds
# coordination/tools/comms-watch/).
# Stop it with: tmux kill-session -t comms-watch
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="${WORKSPACE:-$(cd "$D/../../.." && pwd)}"
PROFILE="$WORKSPACE/coordination/permission-profiles/watcher.json"
[[ -d "$WORKSPACE/coordination" ]] || { echo "STOP: no $WORKSPACE/coordination; set WORKSPACE to the workspace root" >&2; exit 1; }
# Claude Code ignores a settings file it can't parse, without an error, and then nothing is denied.
python3 -c "import json,sys; json.load(open(sys.argv[1]))['permissions']['deny']" "$PROFILE" ||
  { echo "STOP: $PROFILE is missing or not valid JSON with a permissions.deny list" >&2; exit 1; }
if grep -q -E '<[A-Za-z][^<>"]*>' "$PROFILE"; then echo "STOP: $PROFILE still has a <placeholder>" >&2; exit 1; fi
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$D/config.json" ||
  { echo "STOP: $D/config.json is missing or not valid JSON" >&2; exit 1; }
if grep -q -E '<[A-Za-z][^<>"]*>' "$D/config.json"; then echo "STOP: $D/config.json still has a <placeholder>" >&2; exit 1; fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "STOP: pass.py needs python3 3.9 or later" >&2; exit 1; }
if tmux has-session -t =comms-watch 2>/dev/null; then echo "comms-watch is already running"; exit 0; fi
# tmux runs the command with the tmux server's environment, whose PATH may differ from ours.
claude_bin=$(command -v claude) || { echo "STOP: claude is not on PATH" >&2; exit 1; }
tmux new-session -d -s comms-watch -c "$D" \
  "$(printf '%q ' env "PATH=$PATH" "CLAUDE_BIN=$claude_bin" "WORKSPACE=$WORKSPACE" "$D/loop.sh")"
echo "comms-watch started (tmux attach -t comms-watch to look); digests in $D/state/digests/"
