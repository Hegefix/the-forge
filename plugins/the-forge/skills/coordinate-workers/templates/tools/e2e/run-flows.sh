#!/usr/bin/env bash
# Run Maestro flows one by one and print only a short result, so an agent doesn't read Maestro's output:
# e2e runs are long, and every line an agent reads stays in its context. Full logs stay on disk; read one
# only when its flow fails.
#
# Usage: run-flows.sh <device-id> <repo-dir> <flow> [flow ...]
#   flow = a file name in <repo-dir>/$FLOWS_DIR (default e2e/maestro), with or without .yaml, e.g. smoke login
# Flows that need a signed-in app need a sign-in first; this script never signs in.
# Output: one line per flow (PASS/FAIL, seconds, the failing step), then "N/M passed in Ts" and the log folder.
# Logs go to ./logs next to this script and are deleted after 2 days. Exit code: 0 when all passed, 1 otherwise.
set -uo pipefail
[ $# -ge 3 ] || { sed -n 2,10p "$0"; exit 2; }
DEVICE=$1; REPO=$2; shift 2
FLOWS_DIR=${FLOWS_DIR:-e2e/maestro}
LOG_ROOT="$(cd "$(dirname "$0")" && pwd)/logs"
LOGS="$LOG_ROOT/$(date +%Y-%m-%d_%H%M%S)_$DEVICE"
mkdir -p "$LOGS"
find "$LOG_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +2 -exec rm -rf {} + 2>/dev/null
export MAESTRO_CLI_NO_ANALYTICS=1
pass=0; total=0; start_all=$(date +%s)
for f in "$@"; do
  name=${f%.yaml}; file="$REPO/$FLOWS_DIR/$name.yaml"
  total=$((total + 1))
  if [ ! -f "$file" ]; then echo "FAIL $name: no such flow ($file)"; continue; fi
  s=$(date +%s)
  maestro --device "$DEVICE" test "$file" > "$LOGS/$name.log" 2>&1
  rc=$?; secs=$(( $(date +%s) - s ))
  if [ $rc -eq 0 ]; then
    pass=$((pass + 1)); echo "PASS $name ${secs}s"
  else
    why=$(grep -E "FAILED|Assertion|not found|Element not|Unable|Error|Timeout" "$LOGS/$name.log" | grep -v -E "^\s*$" | tail -1 | cut -c1-160)
    echo "FAIL $name ${secs}s: ${why:-exit $rc, see the log}"
  fi
done
echo "$pass/$total passed in $(( $(date +%s) - start_all ))s · logs: $LOGS"
[ $pass -eq $total ]
