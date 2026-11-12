#!/usr/bin/env bash
# Checks the tools, the qa-run config and the booted devices. Prints one line per item.
# Usage: preflight.sh [config-file]   (default: .claude/qa-run.json)
# Exit 0 when nothing blocks a run, 1 otherwise.
set -uo pipefail
cfg=${1:-.claude/qa-run.json}
bad=0
ok() { echo "ok      $1"; }
no() { echo "MISSING $1"; bad=1; }
have() { command -v "$1" >/dev/null 2>&1; }

have xcrun && xcrun simctl help >/dev/null 2>&1 && ok "Xcode simulators" || no "Xcode simulators (setup-mac.md, part 1)"
have adb && ok "adb" || no "adb (setup-mac.md, part 2)"
have emulator && ok "Android emulator" || no "emulator on PATH (setup-mac.md, part 2)"
if have java && java -version 2>&1 | grep -q -E 'version "(1[7-9]|2[0-9])'; then ok "Java 17+"; else no "Java 17+ (setup-mac.md, part 3)"; fi
have maestro && ok "Maestro $(maestro --version 2>/dev/null | tail -1)" || no "Maestro (setup-mac.md, part 4)"
have jq && ok "jq" || no "jq (brew install jq)"

if [ -f "$cfg" ] && have jq; then
  ok "config $cfg"
  left=$(jq -r '[.. | (objects | keys[]), (.. | strings) | select(test("^<.*>$"))] | length' "$cfg")
  [ "$left" = 0 ] && ok "config has no placeholders left" || { echo "TODO    $left placeholder(s) left in $cfg:"; jq -r 'paths as $p | (($p|last|tostring) as $k | getpath($p) as $v | select(($k|test("^<.*>$")) or (($v|type)=="string" and ($v|test("^<.*>$"))))) | "          " + ($p|map(tostring)|join("."))' "$cfg"; }
else
  no "config $cfg (copy templates/qa-run.json, see references/config.md)"
fi

echo "Booted iOS simulators:"; have xcrun && xcrun simctl list devices booted 2>/dev/null | grep -E "Booted" | sed 's/^ */  /' || true
echo "Running Android devices:"; have adb && adb devices 2>/dev/null | sed -n '2,$p' | grep -v '^$' | sed 's/^/  /' || true
exit $bad
