# Helpers

Loop sessions and scripts that save the coordinator work. Copy the folders you want to `<workspace>/coordination/tools/`. The scripts find the workspace from their own place (three folders up), or from `WORKSPACE` if you set it. State, logs and reports stay next to each script.

| Helper | Files | Kind | Needs |
|---|---|---|---|
| [Comms watcher](#comms-watcher) | `comms-watch/WATCH.md`, `start.sh` | Claude session on a loop, `watcher` profile | `tmux`, read access to chat, git hosting and the tracker |
| [MR watch](#mr-watch) | `mr-watch/watch_mrs.py`, `wait_event.py`, `start.sh`, `mrs.txt` | script | `tmux`, `python3`, `glab` logged in, GitLab |
| [Scribe](#scribe-optional) (optional) | `scribe/SCRIBE.md`, `start.sh`, `push.sh` | Claude session on a loop, `watcher` profile | `tmux`, a knowledge base the session can write to; `git` if it is a git repo |
| [Janitor](#janitor) | `janitor/janitor.py`, `start.sh` | script | `tmux`, `python3` 3.9+, `glab` logged in, GitLab |
| [Load check](#load-check) | `load-check/load.sh`, `watch.sh`, `start.sh`, `wait_change.sh` | scripts | macOS, `tmux` |
| [e2e runner](#e2e-runner) | `e2e/run-flows.sh` | script | Maestro |
| [Tracker helper](#tracker-helper) | `tracker/md2adf.py` | script, run by hand | `python3`; a tracker that stores ADF (Jira, Confluence) |

Pick what fits. No helper depends on another one: each works alone, and so does the coordinator without any of them.

The two loop sessions need `coordination/permission-profiles/watcher.json` filled in ([permission profiles](../permission-profiles/README.md)). Their `start.sh` refuses a profile that is missing, isn't valid JSON or still has a `<placeholder>`. They run with `--permission-mode auto` by default, so a pass never stops at a prompt (`PERMISSION_MODE` changes it), and read the workspace `CLAUDE.md`'s "Coordination settings" for the coordinator's session name, the decision log, the notes and the working hours.

## Comms watcher

Every 10 minutes it reads what's new in chat, git hosting and the tracker, labels each item (`human`, `judgment`, `mechanical`, `fyi`, `noise`) and sends the coordinator one digest. It never replies, reacts or posts.

1. Fill in "Comms watcher sources" in the workspace `CLAUDE.md`: who the human is on each service, which channels, which DMs, the MR query and the tracker query.
2. `coordination/tools/comms-watch/start.sh` (tmux `comms-watch`; model `haiku` unless `COMMS_WATCH_MODEL` says otherwise).
3. Read its first digests and check them against the sources. `state/log.md` has every item, `state/runs.log` one line per pass.

`WATCH.md` has the lessons already learned: Slack's `after:` filter excludes that day, an empty DM search is a reason to run the backup, a merged MR's target branch matters, and a tracker update counts as "own" only by the comment authors.

## MR watch

Every 90 seconds, with no model, it reads your open MRs in every project (and the ones listed in `mrs.txt`) and appends one line per change to `events.log`: state, draft, merge status, a finished pipeline, approvers, a new comment by someone else, and the target branch of a merge. The comms watcher's digest comes every 10 minutes; this is the fast path for your own MRs, so the coordinator merges or fixes as soon as an approval or a red pipeline lands.

1. `coordination/tools/mr-watch/start.sh` (tmux `mr-watch`).
2. The coordinator keeps `python3 -I coordination/tools/mr-watch/wait_event.py` running in the background. It returns with the new lines; start it again after each one.

Settings (environment): `MR_WATCH_AUTHOR` (default: the user `glab` is logged in as), `MR_WATCH_IGNORE` (usernames whose comments aren't news, such as you and a code-quality bot), `MR_WATCH_HOST`, `MR_WATCH_INTERVAL` (default 90 s). Add MRs of others to `mrs.txt`; it is read on every pass.

## Scribe (optional)

Optional: if you keep an LLM wiki or knowledge base (an MCP server such as an Obsidian vault, or a folder of notes). Without it, the coordinator keeps the decision log and refreshes the handover note's "State" itself, and nothing else changes.

Every 20 minutes it reads the new lines of the decision log (and the evidence they point to) and rewrites the dashboard, the handover note's "State" and the knowledge notes. The coordinator keeps the log specific and sends it `save: <conclusion>` for anything else worth a note.

1. Set the knowledge base and the dashboard in "Coordination settings" (plain files in `coordination/notes/` work too).
2. If the notes are a git repo with a remote, start with `NOTES_REPO=<path> coordination/tools/scribe/start.sh`; the scribe then runs `push.sh` after each pass that changed something. Otherwise just `coordination/tools/scribe/start.sh`.
3. The first pass sets its cursor to the current end of the log, so it only picks up what comes after.

## Janitor

Every 10 minutes, with no model, it removes the worktrees under `.worktrees/` whose MR is merged or closed (with the local branch, and the remote branch of a merged MR), and once a day it deletes native build output in worktrees idle for 24 hours. It never touches a dirty worktree, unpushed commits, a branch without an MR, someone else's MR or the default branch. It reports those in `state/report.log`.

1. Try it: `python3 -I coordination/tools/janitor/janitor.py --once --dry-run`.
2. `coordination/tools/janitor/start.sh` (tmux `janitor`).
3. The coordinator keeps `python3 -I coordination/tools/janitor/janitor.py --wait` running in the background. It returns with the new report lines.

Settings (environment): `JANITOR_AUTHOR` (your GitLab username; by default the user `glab` is logged in as), `JANITOR_CLEAN_HOUR` (default 19; a clean missed because the laptop was asleep runs on the next pass), `JANITOR_BUILD_DIRS` (default `ios/build:android/app/build:android/build:android/.gradle`). It talks to GitLab only. For GitHub, `mrs_for()` would ask `gh pr list --head <branch> --state all` instead.

## Load check

`load.sh` prints a verdict first: GREEN (go), YELLOW (finish the running device job, no new agent, one platform at a time) or RED (pause the device queue, start nothing, close idle agents). Then load per core, swap, free memory, thermal warnings, booted simulators and emulators, the number of worker sessions, the three **biggest agents** by transcript size, and the top CPU processes. Swap alone only ever makes it YELLOW, because macOS keeps swap long after the pressure is gone.

1. `coordination/tools/load-check/start.sh` starts load-watch (tmux `load-watch`): `load.sh` every minute into `state`, verdict changes into `events.log`.
2. The coordinator keeps `coordination/tools/load-check/wait_change.sh` running in the background. It returns when the verdict changes.

Set `LOAD_SKIP_SESSIONS` (a regex, default `janitor|load-watch|mr-watch`) to the tmux sessions that run no Claude session, so they don't count as agents.

## e2e runner

`run-flows.sh <device-id> <repo-dir> <flow> [flow …]` runs Maestro flows one at a time and prints one line per flow (PASS or FAIL, seconds, the failing step), then `N/M passed`. The full output stays in `logs/` next to the script for 2 days. An agent reads a log only for a failed flow, so a long run costs a few lines of context instead of thousands. Flows live in `<repo-dir>/e2e/maestro/` unless `FLOWS_DIR` says otherwise. It never signs in.

For another e2e tool, keep the shape: one short line per test, logs on disk, a non-zero exit code when one failed.

## Tracker helper

`md2adf.py <file.md | ->` turns Markdown into Atlassian Document Format (ADF). A tracker that stores ADF (Jira, Confluence) shows `- [ ] item` sent as Markdown as plain text. Sent as ADF, it becomes a real checkbox that QA can tick, and that an agent ticks after merge with the evidence. Use it for tickets with "Acceptance criteria" and "Technical requirements" lists, and for evidence comments. It handles headings, paragraphs, bullet lists, task lists and inline code; anything else stays plain text.

Two tracker rules that go with it:

- **Look transitions up by the target status name, never by a hard-coded id.** Transition ids differ per issue type, so an id that means "In Review" on one type can mean "Blocked" on another.
- **Work that starts now goes into the active sprint; planned work goes to the backlog.** A milestone's tickets or a later follow-up enter a sprint at planning, or when work starts.
