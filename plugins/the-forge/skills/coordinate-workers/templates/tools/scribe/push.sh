#!/usr/bin/env bash
# Push the notes repo after a scribe pass changed notes. pass.py runs it: the pass itself has no shell, and the
# watcher profile denies `git push`, so this script is the only way notes reach their remote. It pushes nothing
# but the notes repo's current branch, never with force.
#   NOTES_REPO=<repo> push.sh [<path> …]
# With paths (plain-file notes): commits those paths first, and nothing else in the repo.
# Without paths (a notes MCP server that commits its own changes): pushes only.
# Either way it refuses to push while the repo has other uncommitted changes to tracked files.
# An https remote that needs the GitHub CLI's login: add
#   -c credential.helper= -c credential.helper='!gh auth git-credential'
# after `git -C "$R"` in the push line. It uses that login for this one push and changes no git config.
set -euo pipefail
R="${NOTES_REPO:-}"
[[ -n "$R" ]] || { echo "NOTES_REPO is not set; nothing to push"; exit 0; }
if (( $# )); then
  git -C "$R" add -A -- "$@"
  git -C "$R" diff --cached --quiet -- "$@" || git -C "$R" commit -q -m "scribe: update notes" -- "$@"
fi
git -C "$R" diff --quiet --ignore-submodules HEAD -- || { echo "$R has uncommitted changes; not pushing"; exit 1; }
B=$(git -C "$R" rev-parse --abbrev-ref HEAD)
git -C "$R" push origin "$B" 2>&1 | tail -2
git -C "$R" status -sb | head -1
