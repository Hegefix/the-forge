#!/bin/bash
# Starts a worker through launch-worker.sh only if the token budget allows it. Use this instead of
# launch-worker.sh when the workspace runs the token meter (coordination/tools/token-meter/).
#
# Usage: launch-gated.sh <launch-worker.sh arguments>     (--model sonnet for a smaller model)
#
#   GREEN   any model, up to max_big_workers live workers on a big model (budget.json, default 3)
#   YELLOW  a smaller model only (--model sonnet or haiku)
#   RED     nothing new: running workers finish their step and checkpoint
#
# A worker runs on a big model unless --model names sonnet or haiku. Live big-model workers are counted from
# the process list: `claude --name <worker>` without --model sonnet|haiku and without -p (a headless pass).
# The gate fails closed: if the meter cannot give a verdict (budget.json not filled in), it stops.
# BUDGET_OVERRIDE=1 skips the gate for one launch. Set it only when the human said so for that launch.
#
# On a stop it prints `STOP: <reason>` and exits 3. Otherwise it runs launch-worker.sh with the same arguments.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
args=("$@")
workspace="$PWD" model=""
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[i]}" in
    --workspace) workspace="${args[i + 1]:-$PWD}" ;;
    --model) model="${args[i + 1]:-}" ;;
  esac
done
workspace=$(cd "$workspace" 2>/dev/null && pwd) || { echo "STOP: workspace not found: $workspace"; exit 3; }
meter="$workspace/coordination/tools/token-meter/meter.py"
budget="$workspace/coordination/tools/token-meter/budget.json"

big=true
[[ "$model" == *sonnet* || "$model" == *haiku* ]] && big=false

if [[ "${BUDGET_OVERRIDE:-0}" != 1 ]]; then
  [[ -f "$meter" ]] || { echo "STOP: no token meter at $meter (copy templates/tools/token-meter/ there)"; exit 3; }
  line=$(python3 -I "$meter" gate | tail -1)
  verdict=${line%% *}
  echo "BUDGET: $line"
  case "$verdict" in
    GREEN) ;;
    YELLOW) $big && { echo "STOP: budget YELLOW, a smaller model only (--model sonnet)"; exit 3; } ;;
    RED) echo "STOP: budget RED, no new workers"; exit 3 ;;
    *) echo "STOP: no budget verdict, fix the token meter's budget.json"; exit 3 ;;
  esac
  if $big; then
    max=$(python3 -I -c 'import json,sys; print(int(json.load(open(sys.argv[1])).get("max_big_workers", 3)))' "$budget" 2>/dev/null || echo 3)
    n=$(ps -axo command | grep -E '(^|/)claude .*--name ' | grep -v -E -- '--model [a-z0-9.-]*(sonnet|haiku)| -p ' | grep -vc grep)
    ((n >= max)) && { echo "STOP: $n workers on a big model are running (max $max); wait for one to finish or use --model sonnet"; exit 3; }
  fi
fi
exec bash "$HERE/launch-worker.sh" "$@"
