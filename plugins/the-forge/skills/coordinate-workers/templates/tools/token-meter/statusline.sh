#!/usr/bin/env bash
# statusLine command for the coordinator session only (see tools README, "Token meter"). Claude Code pipes the
# session JSON on stdin. When it carries rate_limits (the plan's real usage, as in /usage), save them for
# meter.py and print a short line. No API calls, no credentials. Needs jq. The field may be absent (some plans,
# or before the first reply); the meter then falls back to its estimate.
D="$(cd "$(dirname "$0")" && pwd)/state"
mkdir -p "$D"
in="$(cat)"
rl="$(printf '%s' "$in" | jq -c '.rate_limits // empty' 2>/dev/null)"
if [ -n "$rl" ]; then
  printf '{"saved_at":%s,"rate_limits":%s}\n' "$(date +%s)" "$rl" > "$D/rate_limits.json.tmp" && mv "$D/rate_limits.json.tmp" "$D/rate_limits.json"
  printf '%s' "$rl" | jq -r '"week \(.seven_day.used_percentage // "?" | if type=="number" then floor else . end)% (reset \(.seven_day.resets_at // 0 | strflocaltime("%a %H:%M"))) · 5h \(.five_hour.used_percentage // "?" | if type=="number" then floor else . end)%"'
else
  echo "week: no rate_limits in statusline input"
fi
