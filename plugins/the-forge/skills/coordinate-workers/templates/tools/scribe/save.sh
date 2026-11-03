#!/usr/bin/env bash
# Leave a note for the scribe: a conclusion worth keeping that isn't in the decision log.
#   coordination/tools/scribe/save.sh "<conclusion>"
# One file per note in state/inbox/. The next gate check sees it and runs a pass; the pass handles the note and
# the shell moves it to state/inbox/done/.
set -euo pipefail
[[ $# -ge 1 && -n "$1" ]] || { echo "usage: $0 \"<note>\"" >&2; exit 2; }
D="$(cd "$(dirname "$0")" && pwd)"
IN="${STATE_DIR:-$D/state}/inbox"
mkdir -p "$IN"
NAME="$(date -u +%Y%m%dT%H%M%SZ)-$$.md"
printf '%s\n' "$*" > "$IN/.$NAME.tmp"
mv "$IN/.$NAME.tmp" "$IN/$NAME"
echo "queued for the scribe: $IN/$NAME"
