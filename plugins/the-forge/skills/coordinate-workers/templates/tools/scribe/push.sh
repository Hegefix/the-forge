#!/usr/bin/env bash
# Push the notes repo after the scribe wrote notes. The scribe's watcher profile denies `git push`, so this
# script is its only way to push: it pushes nothing but the notes repo's current branch, never with force.
# NOTES_REPO (the notes repo's path) comes from start.sh. Without it there is nothing to push.
# An https remote that needs the GitHub CLI's login: add
#   -c credential.helper= -c credential.helper='!gh auth git-credential'
# after `git -C "$R"` in the push line. It uses that login for this one push and changes no git config.
set -euo pipefail
R="${NOTES_REPO:-}"
[[ -n "$R" ]] || { echo "NOTES_REPO is not set; nothing to push"; exit 0; }
git -C "$R" diff --quiet --ignore-submodules HEAD -- || { echo "$R has uncommitted changes; not pushing"; exit 1; }
B=$(git -C "$R" rev-parse --abbrev-ref HEAD)
git -C "$R" push origin "$B" 2>&1 | tail -2
git -C "$R" status -sb | head -1
