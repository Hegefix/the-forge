#!/usr/bin/env bash
# Laptop load check for the coordinator: may another agent or device job start now?
# macOS, built-in tools only. Prints one verdict line first, then the numbers:
#   GREEN  hand the devices to the next agent; a new agent may start
#   YELLOW let the running device job finish, start no new agent, one platform at a time
#   RED    pause the device queue, start nothing, close idle agents, check again in a few minutes
# It also lists the biggest live agents by transcript size, a proxy for their context and so for what
# each of their turns costs.
# Settings (environment): LOAD_SKIP_SESSIONS, a regex of tmux sessions that run no Claude session
# (default: janitor|load-watch|mr-watch).
set -uo pipefail
ncpu=$(sysctl -n hw.ncpu)
read -r l1 l5 l15 < <(sysctl -n vm.loadavg | tr -d '{}')
swap_mb=$(sysctl -n vm.swapusage | sed -E 's/.*used = ([0-9.]+)M.*/\1/')
free_pct=$(memory_pressure -Q 2>/dev/null | sed -nE 's/.*free percentage: ([0-9]+)%.*/\1/p')
therm=$(pmset -g therm 2>/dev/null | grep -v -i 'no .* has been recorded' | grep -i -E 'warning|limit' | head -1)
ios=$(xcrun simctl list devices booted 2>/dev/null | grep -c Booted)
android=$(adb devices 2>/dev/null | grep -c -E '^emulator-[0-9]+\s+device')
agents=$(tmux ls 2>/dev/null | cut -d: -f1 | grep -c -- '--')
claudes=$(pgrep -x claude | wc -l | tr -d ' ')

lvl=0; why=()
bump() { (( $1 > lvl )) && lvl=$1; why+=("$2"); }
# The 5-minute average: a 1-minute peak during a native build is normal and passes in minutes.
ratio=$(awk -v l="$l5" -v n="$ncpu" 'BEGIN{printf "%.2f", l/n}')
awk -v r="$ratio" 'BEGIN{exit !(r>=1.5)}' && bump 2 "load (5 min) ${l5}/${ncpu} cores = ${ratio}x" \
  || { awk -v r="$ratio" 'BEGIN{exit !(r>=0.8)}' && bump 1 "load ${ratio}x"; }
# Swap only ever warns: macOS keeps it long after the pressure is gone, so it can't gate on its own.
awk -v s="$swap_mb" 'BEGIN{exit !(s>=8192)}' && bump 1 "swap ${swap_mb%.*} MB"
[[ -n "$free_pct" ]] && { (( free_pct <= 15 )) && bump 2 "memory free ${free_pct}%" || { (( free_pct <= 30 )) && bump 1 "memory free ${free_pct}%"; }; }
[[ -n "$therm" ]] && bump 2 "thermal: $therm"

verdict=(GREEN YELLOW RED)
echo "${verdict[$lvl]}${why:+ — ${why[*]}}"
echo "load 1/5/15 min: $l1 $l5 $l15 (${ncpu} cores) | swap used: ${swap_mb%.*} MB | memory free: ${free_pct:-?}% | thermal: ${therm:-none}"
echo "booted: iOS sims $ios, Android emulators $android | worker tmux sessions $agents | claude processes $claudes"
# Biggest live agents: the newest transcript in each tmux session's folder. Claude Code keeps transcripts
# in <config>/projects/<cwd with '/' and '.' as '-'>/<session id>.jsonl.
projects="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"
for s in $(tmux ls -F '#{session_name}' 2>/dev/null | grep -v -x -E "${LOAD_SKIP_SESSIONS:-janitor|load-watch|mr-watch}"); do
  d="$projects/$(tmux display -p -t "=$s:" '#{session_path}' | sed 's#[/.]#-#g')"
  f=$(ls -t "$d"/*.jsonl 2>/dev/null | head -1)
  [ -n "$f" ] && echo "$(du -m "$f" | cut -f1) $s"
done | sort -rn | head -3 | awk '{printf "%s%s %s MB", (NR>1?", ":"biggest agents: "), $2, $1} END{if (NR) print ""}'
echo "top CPU:"
ps -A -o %cpu=,rss=,comm= | sort -rn | awk 'NR<=5{n=split($3,p,"/"); printf "  %5.1f%% CPU %6.0f MB  %s\n",$1,$2/1024,p[n]}' || true
exit 0
