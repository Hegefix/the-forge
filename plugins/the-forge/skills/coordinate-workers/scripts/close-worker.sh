#!/bin/bash
# Closes workers: each one's Terminal window first, then its tmux session.
#
# Usage:
#   close-worker.sh <tmux-session> [<tmux-session> ...]
#
# The window goes first: Terminal closes a window that only runs tmux without asking, and after the
# kill its title no longer names the session. launch-worker.sh opens each window with
# `tmux attach -t <session>`, and Terminal shows that command in the title, followed by " — ".
# A window whose title doesn't match stays open, detached; the session is killed either way.
#
# Prints `closed <session>` per session, or `no tmux session <session>`.
set -uo pipefail

(($#)) || { echo "usage: close-worker.sh <tmux-session> [<tmux-session> ...]" >&2; exit 2; }
if [[ "$1" == -h || "$1" == --help ]]; then
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
  exit 0
fi

for session in "$@"; do
  if command -v osascript >/dev/null; then
    # The " —" after the name keeps `foo` from matching the window of `foo-bar`.
    osascript -e "tell application \"Terminal\" to close (every window whose name contains \"tmux attach -t $session —\")" \
      >/dev/null 2>&1 || true
  fi
  if tmux kill-session -t "=$session" 2>/dev/null; then
    echo "closed $session"
  else
    echo "no tmux session $session"
  fi
done
