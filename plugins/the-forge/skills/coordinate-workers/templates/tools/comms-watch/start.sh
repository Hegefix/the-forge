#!/usr/bin/env bash
# Start the comms watcher: a read-only Claude session in tmux session "comms-watch" that runs WATCH.md every
# 10 minutes and sends the coordinator one digest of what's new in chat, git hosting and the issue tracker.
# It runs with the watcher profile: chat reads only, no chat, tracker or git hosting writes, no edits in
# repos or worktrees.
# Settings (environment): WORKSPACE (default: the folder that holds coordination/tools/comms-watch/),
# COMMS_WATCH_MODEL (default: haiku; a pass is reading and sorting), PERMISSION_MODE (default: auto, so the
# loop never waits on a prompt).
# Stop it with: tmux kill-session -t comms-watch
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="${WORKSPACE:-$(cd "$D/../../.." && pwd)}"
PROFILE="$WORKSPACE/coordination/permission-profiles/watcher.json"
[[ -f "$WORKSPACE/CLAUDE.md" ]] || { echo "STOP: no $WORKSPACE/CLAUDE.md; set WORKSPACE to the workspace root" >&2; exit 1; }
# Claude Code ignores a settings file it can't parse, without an error, and then nothing is denied.
python3 -c "import json,sys; json.load(open(sys.argv[1]))['permissions']['deny']" "$PROFILE" ||
  { echo "STOP: $PROFILE is missing or not valid JSON with a permissions.deny list" >&2; exit 1; }
if grep -q -E '<[A-Za-z][A-Za-z0-9_-]*>' "$PROFILE"; then echo "STOP: $PROFILE still has a <placeholder>" >&2; exit 1; fi
if tmux has-session -t =comms-watch 2>/dev/null; then echo "comms-watch is already running"; exit 0; fi
# tmux runs the command with the tmux server's environment, whose PATH may differ from ours.
claude_bin=$(command -v claude) || { echo "STOP: claude is not on PATH" >&2; exit 1; }
args=("$claude_bin" --model "${COMMS_WATCH_MODEL:-haiku}" --permission-mode "${PERMISSION_MODE:-auto}"
  --settings "$PROFILE" --name comms-watch)
prompt="/loop 10m Run one pass of $D/WATCH.md (workspace: $WORKSPACE). Keep the loop running; never cancel it."
tmux new-session -d -s comms-watch -c "$D" "$(printf '%q ' "${args[@]}" "$prompt")"
echo "comms-watch started (tmux attach -t comms-watch to look)"
