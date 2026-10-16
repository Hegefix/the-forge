#!/usr/bin/env bash
# Start the scribe: a Claude session in tmux session "scribe" that runs SCRIBE.md every 20 minutes and
# keeps the team's notes (dashboard, the handover note's State, knowledge notes) current from the decision log.
# It runs with the watcher profile: no chat, tracker or git hosting writes, no edits in repos or worktrees.
# Settings (environment): WORKSPACE (default: the folder that holds coordination/tools/scribe/),
# NOTES_REPO (the notes' git repo, for push.sh; leave it unset for notes that aren't a git repo),
# SCRIBE_MODEL (default: your default model), PERMISSION_MODE (default: auto, so the loop never waits on a prompt).
# Stop it with: tmux kill-session -t scribe
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="${WORKSPACE:-$(cd "$D/../../.." && pwd)}"
PROFILE="$WORKSPACE/coordination/permission-profiles/watcher.json"
[[ -f "$WORKSPACE/CLAUDE.md" ]] || { echo "STOP: no $WORKSPACE/CLAUDE.md; set WORKSPACE to the workspace root" >&2; exit 1; }
# Claude Code ignores a settings file it can't parse, without an error, and then nothing is denied.
python3 -c "import json,sys; json.load(open(sys.argv[1]))['permissions']['deny']" "$PROFILE" ||
  { echo "STOP: $PROFILE is missing or not valid JSON with a permissions.deny list" >&2; exit 1; }
if grep -q -E '<[A-Za-z][A-Za-z0-9_-]*>' "$PROFILE"; then echo "STOP: $PROFILE still has a <placeholder>" >&2; exit 1; fi
if tmux has-session -t =scribe 2>/dev/null; then echo "scribe is already running"; exit 0; fi
# tmux runs the command with the tmux server's environment, whose PATH may differ from ours.
claude_bin=$(command -v claude) || { echo "STOP: claude is not on PATH" >&2; exit 1; }
args=("$claude_bin" --permission-mode "${PERMISSION_MODE:-auto}" --settings "$PROFILE" --name scribe)
args+=(--model "${SCRIBE_MODEL:-sonnet}")  # a mid-size model is enough for summarising the log into notes
prompt="/loop 20m Run one pass of $D/SCRIBE.md (workspace: $WORKSPACE). Keep the loop running; never cancel it."
tmux new-session -d -s scribe -c "$D" -e "NOTES_REPO=${NOTES_REPO:-}" "$(printf '%q ' "${args[@]}" "$prompt")"
echo "scribe started (tmux attach -t scribe to look)"
