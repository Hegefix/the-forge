#!/usr/bin/env bash
# Runs Maestro flows one by one and prints one short line each, so nobody reads Maestro's long output.
# Full logs stay on disk; read one only for a failed flow. A failed flow is rerun once; a pass on rerun is a FLAKE.
#
# Usage: run-flows.sh <device-id> <flows-dir> <flow> [flow ...]
#   flow = a file name in <flows-dir>, with or without .yaml
# Environment: QA_LOGS = log folder (default: ./qa-logs/<time>_<device>)
# Signing in is not done here: run the project's sign-in command first.
# Output: PASS / FAIL / FLAKE per flow, then "N/M passed" and the log folder. Exit 0 only when all passed first time or on rerun.
set -uo pipefail
[ $# -ge 3 ] || { sed -n 2,11p "$0"; exit 2; }
dev=$1; dir=$2; shift 2
logs=${QA_LOGS:-./qa-logs/$(date +%Y-%m-%d_%H%M%S)_$dev}
mkdir -p "$logs"
export MAESTRO_CLI_NO_ANALYTICS=1
pass=0; total=0; flakes=0; start=$(date +%s)

run_one() { maestro --device "$dev" test "$1" > "$2" 2>&1; }

for f in "$@"; do
  name=${f%.yaml}; file="$dir/$name.yaml"; total=$((total + 1))
  [ -f "$file" ] || { echo "FAIL  $name: no such flow ($file)"; continue; }
  s=$(date +%s)
  if run_one "$file" "$logs/$name.log"; then
    pass=$((pass + 1)); echo "PASS  $name $(( $(date +%s) - s ))s"; continue
  fi
  why=$(grep -E "FAILED|Assertion|not found|Element not|Unable|Error|Timeout" "$logs/$name.log" | tail -1 | cut -c1-160)
  if run_one "$file" "$logs/$name.rerun.log"; then
    pass=$((pass + 1)); flakes=$((flakes + 1)); echo "FLAKE $name: failed once (${why:-see log}), passed on rerun"
  else
    why2=$(grep -E "FAILED|Assertion|not found|Element not|Unable|Error|Timeout" "$logs/$name.rerun.log" | tail -1 | cut -c1-160)
    echo "FAIL  $name $(( $(date +%s) - s ))s: ${why2:-exit, see the log}"
  fi
done
echo "$pass/$total passed ($flakes flake) in $(( $(date +%s) - start ))s · logs: $logs"
[ "$pass" -eq "$total" ]
