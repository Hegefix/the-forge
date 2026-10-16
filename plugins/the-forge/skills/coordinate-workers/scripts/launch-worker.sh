#!/bin/bash
# Starts one worker: a git worktree for the task, a detached tmux session running Claude Code in
# it with the brief as its first prompt, and a new macOS Terminal window attached to that session.
#
# Usage:
#   launch-worker.sh --repo <path> --task <slug> --name <worker-name> --brief <file>
#                    [--branch <name>] [--base <ref>] [--workspace <dir>]
#                    [--permission-mode <mode>] [--profile <name|path>]
#                    [--reuse-worktree] [--no-window] [--dry-run]
#
#   --repo             any checkout of the target repository
#   --task             short slug; names the worktree folder and the tmux session
#   --name             the worker's session name, which SendMessage addresses. The coordinator picks
#                      it: neutral by default (<repo>-<task> or the task slug, lowercase ASCII, unique
#                      among live sessions), or the workspace's own scheme. It never changes while
#                      the worker runs.
#   --brief            file whose text becomes the worker's first prompt
#   --branch           new branch name (default: the task slug)
#   --base             start point (default: the remote's default branch, freshly fetched)
#   --workspace        coordinator workspace root (default: the current directory)
#   --permission-mode  passed to `claude --permission-mode` (default: the user's own default)
#   --profile          permission profile, passed to `claude --settings`: a name such as `code`
#                      (<workspace>/coordination/permission-profiles/<name>.json) or a path to a
#                      JSON file. Refused if missing, not valid JSON or still holding a <placeholder>.
#   --reuse-worktree   start the worker in an existing worktree at the target path
#   --no-window        don't open a Terminal window; print the attach command instead
#   --dry-run          check everything, print what would run, change nothing
#
# On success it prints KEY: value lines (SESSION, NAME, WORKTREE, BRANCH, BASE, PROFILE, ATTACH).
# On any refusal it prints `STOP: <reason>` and exits non-zero.
set -euo pipefail

stop() {
  echo "STOP: $*" >&2
  exit 1
}

repo="" task="" name="" brief="" branch="" base="" workspace="$PWD" mode="" profile=""
reuse=false window=true dry_run=false

while (($#)); do
  case "$1" in
    --repo | --task | --name | --brief | --branch | --base | --workspace | --permission-mode | --profile)
      (($# >= 2)) || stop "$1 needs a value"
      case "$1" in
        --repo) repo="$2" ;;
        --task) task="$2" ;;
        --name) name="$2" ;;
        --brief) brief="$2" ;;
        --branch) branch="$2" ;;
        --base) base="$2" ;;
        --workspace) workspace="$2" ;;
        --permission-mode) mode="$2" ;;
        --profile) profile="$2" ;;
      esac
      shift 2
      ;;
    --reuse-worktree) reuse=true; shift ;;
    --no-window) window=false; shift ;;
    --dry-run) dry_run=true; shift ;;
    -h | --help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) stop "unknown argument: $1 (see --help)" ;;
  esac
done

[[ -n "$repo" && -n "$task" && -n "$name" && -n "$brief" ]] ||
  stop "--repo, --task, --name and --brief are required (see --help)"
[[ "$task" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] ||
  stop "--task must be a slug of letters, digits, '.', '_' or '-': $task"
[[ -s "$brief" ]] || stop "brief file is missing or empty: $brief"

for cmd in git tmux claude; do
  command -v "$cmd" >/dev/null || stop "$cmd is not on PATH"
done
# tmux runs the command with the tmux server's environment, whose PATH may differ from ours.
claude_bin=$(command -v claude)

brief=$(cd "$(dirname "$brief")" && pwd)/$(basename "$brief")
workspace=$(cd "$workspace" 2>/dev/null && pwd) || stop "workspace not found: $workspace"

if [[ -n "$profile" ]]; then
  # A bare name is looked up in the workspace; anything with a '/' or a .json suffix is a path.
  if [[ "$profile" == */* || "$profile" == *.json ]]; then
    profile_file=$profile
  else
    [[ "$profile" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || stop "--profile must be a name or a path: $profile"
    profile_file="$workspace/coordination/permission-profiles/$profile.json"
  fi
  [[ -s "$profile_file" ]] || stop "permission profile not found or empty: $profile_file"
  profile_file=$(cd "$(dirname "$profile_file")" && pwd)/$(basename "$profile_file")
  if placeholder=$(grep -n -m1 -o -E '<[A-Za-z][A-Za-z0-9_-]*>' "$profile_file"); then
    placeholder=${placeholder%%$'\n'*}
    stop "permission profile $profile_file still has ${placeholder#*:} on line ${placeholder%%:*}; fill it in or delete the line"
  fi
  # Claude Code ignores a settings file it cannot parse, without an error, and then nothing is denied.
  if command -v jq >/dev/null; then
    jq -e '.permissions.deny | type == "array"' "$profile_file" >/dev/null 2>&1 ||
      stop "permission profile is not valid JSON with a permissions.deny list: $profile_file"
  else
    echo "WARN: no jq, so $profile_file was not checked; Claude Code ignores an invalid settings file" >&2
  fi
fi

common_dir=$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) ||
  stop "not a git repository: $repo"
repo_root=$(dirname "$common_dir")
repo_name=$(basename "$repo_root")

# tmux treats ':' and '.' in a target as window and pane separators, so a session named
# `repo:task` cannot be attached by name. Both become '-'.
session=$(printf '%s--%s' "$repo_name" "$task" | tr '.:' '--')
worktree="$workspace/.worktrees/$repo_name/$task"
branch="${branch:-$task}"

if tmux has-session -t "=$session" 2>/dev/null; then
  stop "tmux session $session already exists; attach with: tmux attach -t $session"
fi

if [[ -e "$worktree" ]]; then
  $reuse || stop "$worktree already exists; pass --reuse-worktree to start the worker there"
  [[ "$(git -C "$worktree" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" == "$common_dir" ]] ||
    stop "$worktree exists but is not a worktree of $repo_root"
  branch=$(git -C "$worktree" branch --show-current)
  base="(existing worktree)"
else
  $reuse && stop "--reuse-worktree given, but $worktree does not exist"
  git -C "$repo_root" check-ref-format --branch "$branch" >/dev/null 2>&1 ||
    stop "not a valid branch name: $branch"
  if git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch"; then
    stop "branch $branch already exists; pick another --branch, or reuse its worktree with --reuse-worktree"
  fi
  if ! $dry_run && git -C "$repo_root" remote get-url origin >/dev/null 2>&1; then
    git -C "$repo_root" fetch --quiet origin || stop "git fetch origin failed in $repo_root"
  fi
  if [[ -z "$base" ]]; then
    base=$(git -C "$repo_root" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null) || base=""
    if [[ -z "$base" ]]; then
      for candidate in origin/main origin/master; do
        if git -C "$repo_root" rev-parse --verify --quiet "$candidate^{commit}" >/dev/null; then
          base=$candidate
          break
        fi
      done
    fi
    [[ -n "$base" ]] || stop "cannot tell the default branch of origin; pass --base"
  fi
  git -C "$repo_root" rev-parse --verify --quiet "$base^{commit}" >/dev/null ||
    stop "base ref not found: $base"
fi

claude_args=("$claude_bin")
[[ -n "$mode" ]] && claude_args+=(--permission-mode "$mode")
[[ -n "$profile" ]] && claude_args+=(--settings "$profile_file")
claude_args+=(--name "$name")
# The shell inside tmux reads the brief, so its text is never re-parsed as shell syntax.
tmux_cmd="$(printf '%q ' "${claude_args[@]}")\"\$(cat $(printf '%q' "$brief"))\""
attach="tmux attach -t $session"
osa_cmd="tell application \"Terminal\" to do script \"$(command -v tmux) attach -t $session\""

if $dry_run; then
  [[ "$base" == "(existing worktree)" ]] ||
    echo "WOULD RUN: git -C $repo_root fetch origin && git -C $repo_root worktree add --no-track -b $branch $worktree $base"
  echo "WOULD RUN: tmux new-session -d -s $session -c $worktree '$tmux_cmd'"
  $window && echo "WOULD RUN: osascript -e '$osa_cmd'"
else
  if [[ "$base" != "(existing worktree)" ]]; then
    mkdir -p "$(dirname "$worktree")"
    # --no-track: a branch tracking origin/<default> would make a plain `git push` fail or
    # target the default branch.
    git -C "$repo_root" worktree add --quiet --no-track -b "$branch" "$worktree" "$base" ||
      stop "git worktree add failed"
  fi
  tmux new-session -d -s "$session" -c "$worktree" "$tmux_cmd" || stop "tmux new-session failed"
  if $window; then
    if command -v osascript >/dev/null; then
      # Always a new window. `do script ... in <tab>` would type into a running agent's input.
      osascript -e "$osa_cmd" >/dev/null || echo "WARN: could not open a Terminal window" >&2
    else
      echo "WARN: no osascript (not macOS); attach by hand" >&2
    fi
  fi
fi

echo "SESSION: $session"
echo "NAME: $name"
echo "WORKTREE: $worktree"
echo "BRANCH: $branch"
echo "BASE: $base"
echo "PROFILE: ${profile_file:-(none)}"
echo "ATTACH: $attach"
