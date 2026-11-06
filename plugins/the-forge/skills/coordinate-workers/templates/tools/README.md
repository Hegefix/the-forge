# Helpers

Scripts that save the coordinator work. Two of them, the comms watcher and the scribe, run one headless Claude pass at a time. Copy the folders you want to `<workspace>/coordination/tools/`. The scripts find the workspace from their own place (three folders up), or from `WORKSPACE` if you set it. State, logs and reports stay next to each script.

| Helper | Files | Kind | Needs |
|---|---|---|---|
| [Comms watcher](#comms-watcher) | `comms-watch/PASS.md`, `pass.py`, `config.json`, `loop.sh`, `start-headless.sh`, `wait_digest.py` | shell loop, one headless `claude -p` pass per interval, `watcher` profile | `tmux`, `python3` 3.9+, read access to chat and the tracker; `glab` for the git hosting to-dos |
| [MR watch](#mr-watch) | `mr-watch/watch_mrs.py`, `wait_event.py`, `start.sh`, `mrs.txt` | script | `tmux`, `python3`, `glab` logged in, GitLab |
| [Scribe](#scribe-optional) (optional) | `scribe/PASS.md`, `pass.py`, `config.json`, `loop.sh`, `start-headless.sh`, `save.sh`, `push.sh` | gate with no model, one headless `claude -p` pass only when there is news, `watcher` profile | `tmux`, `python3` 3.9+, notes the pass can write (plain files or an MCP server); `git` if they are a git repo |
| [Janitor](#janitor) | `janitor/janitor.py`, `start.sh` | script | `tmux`, `python3` 3.9+, `glab` logged in, GitLab |
| [Load check](#load-check) | `load-check/load.sh`, `watch.sh`, `start.sh`, `wait_change.sh` | scripts | macOS, `tmux` |
| [Token meter](#token-meter) | `token-meter/meter.py`, `budget.json`, `watch.sh`, `start.sh`, `wait_change.sh`, and `../../scripts/launch-gated.sh` | scripts | macOS or Linux, `tmux`, `python3` 3.9+ |
| [e2e runner](#e2e-runner) | `e2e/run-flows.sh` | script | Maestro |
| [Tracker helper](#tracker-helper) | `tracker/md2adf.py` | script, run by hand | `python3`; a tracker that stores ADF (Jira, Confluence) |

Pick what fits. No helper depends on another one: each works alone, and so does the coordinator without any of them. (The scribe's notices use the comms watcher's `wait_digest.py`; copy that one file if you run the scribe alone.)

## Headless passes

The comms watcher and the scribe are not long-running Claude sessions. A shell loop in tmux runs `pass.py`, and `pass.py` runs one `claude -p` with an empty context, reads its structured result, and writes the files itself: digests, notices, logs, the cursor. No model runs between passes.

- **Why.** A long session on `/loop` re-reads its whole growing context on every pass, and over a day it started to skip reads. In our workspace the `/loop` comms watcher cost about $124 a day, and in 231 passes it read 3 conversations and 4 threads. The headless one starts each pass from a small fixed prompt (7.5k tokens there, against the 55k the `/loop` session carried), and costs about $0.30 per quick pass and $0.60 per full sweep: about $40 a workday. The `/loop` scribe cost $0.48 for a pass with no news and $1.54 for a working one; the headless scribe's gate costs nothing when there is no news.
- **What a pass may do.** `--permission-mode dontAsk` with an allowlist: only the read tools named in `config.json` run (the scribe: plus the write tools of its notes, limited to the notes' paths), and nothing waits on a prompt. No Bash, no other file tools. `watcher.json`'s deny rules apply on top, and `pass.py` refuses to start a pass without a valid profile. Plugins, hooks, `CLAUDE.md` files and auto memory are switched off for the pass, so it starts small and its system prompt stays cached from pass to pass. One exception: a plugin whose MCP server `config.json` names (`plugin_<plugin>_<server>`) stays on, because switching a plugin off also stops its servers. It loads whole, with its skills and its other servers; put those servers in `deny_servers` to keep their tools out of the pass. A source that names only plugin servers, none of them from an installed plugin, fails every pass with `config` in `errors.log`, since it could never connect. `max_usd` and `timeout_s` cap each pass.
- **Settings** are in each helper's `config.json` (strict JSON, no comments). `start-headless.sh` refuses a profile or `config.json` that is missing, isn't valid JSON or still has a `<placeholder>`.
- **Try it before you start the loop:** `python3 -I coordination/tools/<helper>/pass.py --self-check` runs the shell's tests in a throwaway workspace with a stub `claude`. Then one real pass on a copy of the state: `STATE_DIR=state-test python3 -I coordination/tools/comms-watch/pass.py`, and for the scribe `SCRIBE_DRY_RUN=1` too. `state-test/runs.log` shows the cost, the time and, for the comms watcher, what it read; `state-test/last-pass.jsonl` is the whole trace.
- Every pass leaves one line in `state/runs.log`; a failed pass goes to `state/errors.log` and keeps the cursor. After 3 failures in a row, the comms watcher writes a digest and the scribe a notice saying so.
- **Back to `/loop`?** Version 0.2.0 of this plugin ran both helpers as `/loop` sessions (`WATCH.md`, `SCRIBE.md` and their `start.sh`). They are in this repo's history at commit `80c5378`, for example `git show 80c5378:plugins/the-forge/skills/coordinate-workers/templates/tools/comms-watch/WATCH.md`. They read "Comms watcher sources" from the workspace `CLAUDE.md`, and the scribe takes `save:` messages instead of `save.sh`. To switch back: `tmux kill-session -t comms-watch` (or `scribe`), then the old `start.sh`.

## Comms watcher

It reads what's new in chat, the tracker, the wiki, mail and a second chat, plus the git hosting to-dos, labels each item (`human`, `judgment`, `mechanical`, `fyi`, `noise`), and writes one digest file per pass with news to `state/digests/`. It never replies, reacts or posts.

1. Fill in `coordination/tools/comms-watch/config.json` (below), and delete the sources you don't use.
2. Try it (see "Headless passes"), then `coordination/tools/comms-watch/start-headless.sh` (tmux `comms-watch`).
3. The coordinator keeps one waiter running in the background for both helpers' files: `python3 -I coordination/tools/comms-watch/wait_digest.py coordination/tools/comms-watch/state/digests coordination/tools/scribe/state/notices` (leave out the scribe's folder if you don't run it). It returns with the new files; act on them, and start it again.
4. Read its first digests and check them against the sources. `state/log.md` has every item, `state/runs.log` one line per pass.

`config.json`:

| Setting | What it is |
|---|---|
| `schedule`, `otherwise_every_min` | The interval: the first window that matches the day (1 = Monday … 7 = Sunday) and time wins, else `otherwise_every_min`. `0` means no passes. A window that crosses midnight is two windows. The default: working hours only (workdays 09–18, every 20 minutes), no passes otherwise. The first pass of the next window reads everything since the cursor, so nothing is lost overnight; set the window to the team's working hours, and make it busier or add an off-hours window only if someone needs it. |
| `timezone` | IANA name, such as `Europe/Berlin`; empty means this machine's local time. |
| `model`, `max_usd`, `timeout_s` | `sonnet`: a smaller model skipped threads and whole conversations. $3 and 6 minutes per pass. |
| `full_sweep_min`, `lookback_min` | A full sweep reads every conversation every 45 minutes; quick passes in between read only what the activity search shows. The chat window starts 10 minutes early, because search lags. |
| `human` | The human's name as the services show it. Their account's own actions are ours, so they are `noise`. |
| `chat` | The chat server and its read tools; `user_id`, the human's; the key conversations, read on every pass: `key_channels` (recent threads opened too) and `key_dms` (by user id); `watch_people` (everything they post, such as the human's manager). `server` can be a list: the same chat can come as a claude.ai connector and as a plugin server (see the [permission profiles](../permission-profiles/README.md)). |
| `sources` | One entry per other source: `name`, `server`, read `tools`, and `how`, the instruction for the pass. `{minutes}`, `{since_local}` and `{since_utc}` in `how` become the window's start. The template has a tracker (Jira), a wiki (Confluence), mail (Outlook) and a second chat (Teams). |
| `git` | `todos`: the shell fetches the human's GitLab to-dos (mentions, direct addresses, assignments) with `glab`; `username` empty means the user `glab` is logged in as. `mr_watch_runs: true` leaves out the to-dos on the human's own MRs and the MRs they review, because MR watch reports those; with `false` it also passes on review requests, reviews, failed pipelines and unmergeable MRs. |
| `hints` | The workspace's own label rules, one line each, such as "top-level asks in #engineering are at least `judgment`" or "<ticket> is not ours: `noise`". |
| `deny_servers` | MCP servers a pass never needs, so their tool names stay out of its context. |
| `decision_log` | The pass reads its last 30 lines to skip what's already handled. |

**The read check.** For a Slack chat server (`"kind": "slack"`), the first message lists the required chat steps with their exact arguments: the activity search, a read of every conversation and thread it shows, the key conversations, the replies to the human, the watched people, and on a full sweep every conversation. `pass.py` checks the pass's tool calls against them. A missing search counts as a failed chat read: the next pass is a full sweep from the old start. A conversation or thread it didn't read is carried into the next pass as a required read (dropped after 3 tries, since the search still covers it). Each item's message key (Slack channel and ts, Jira comment id) is kept for 48 hours, so the overlap between passes sends nothing twice. Another chat server (`"kind": "other"`) gets the same instructions in words, without the check.

`PASS.md` has the lessons already learned: threads always; an empty search is never "no news"; name a DM by the person who wrote in it; a tracker update counts as "own" only by the comment's author; our own actions are noise; an item already in the decision log is `fyi (handled)`.

## MR watch

Every 90 seconds, with no model, it reads your open MRs in every project (and the ones listed in `mrs.txt`) and appends one line per change to `events.log`: state, draft, merge status, a finished pipeline, approvers, a new comment by someone else, and the target branch of a merge. The comms watcher passes every few minutes; this is the fast path for your own MRs, so the coordinator merges or fixes as soon as an approval or a red pipeline lands.

1. `coordination/tools/mr-watch/start.sh` (tmux `mr-watch`).
2. The coordinator keeps `python3 -I coordination/tools/mr-watch/wait_event.py` running in the background. It returns with the new lines; start it again after each one.

Settings (environment): `MR_WATCH_AUTHOR` (default: the user `glab` is logged in as), `MR_WATCH_IGNORE` (usernames whose comments aren't news, such as you and a code-quality bot), `MR_WATCH_HOST`, `MR_WATCH_INTERVAL` (default 90 s). Add MRs of others to `mrs.txt`; it is read on every pass.

## Scribe (optional)

Optional: if you keep an LLM wiki or knowledge base (an MCP server such as an Obsidian vault, or a folder of notes). Without it, the coordinator keeps the decision log and refreshes the handover note's "State" itself, and nothing else changes.

Every 20 minutes a gate with no model checks the decision log and `state/inbox/`. Only when the log grew or the inbox has a note does one pass run: it reads the new log lines (at most 80 per pass), the inbox notes, the evidence they point to and the other helpers' new log lines, and rewrites the dashboard, the handover note's "State" and the knowledge notes. The coordinator keeps the log specific, and leaves anything else worth a note with `coordination/tools/scribe/save.sh "<conclusion>"`.

1. Fill in `coordination/tools/scribe/config.json` (below). The template works as it is for plain-file notes in `coordination/notes/`.
2. Try it (see "Headless passes", with `SCRIBE_DRY_RUN=1`), then `coordination/tools/scribe/start-headless.sh` (tmux `scribe`).
3. The first pass sets its cursor to the current end of the log, so it only picks up what comes after.
4. Its notices (a new note, a conflict it couldn't resolve, a failed push) land in `state/notices/`; the comms watcher's waiter covers that folder too.

`config.json`:

| Setting | What it is |
|---|---|
| `notes.kind` | `files`: plain files. The pass may Edit and Write only in `notes.dir` and the `handover`, `dashboard` and `app_flows` files (paths from the workspace root). `mcp`: an MCP server (`server`) with its `read_tools` and `write_tools`; `never_tools` (move, rename, delete) are denied; `folders` says where the pass may write, and `handover`, `dashboard` and `app_flows` are note paths there. |
| `notes.rules_file` | Optional: the skill or rules file for your notes, such as the notes server's `SKILL.md` (`~` and globs work). Its text goes into the pass's system prompt. |
| `notes.repo` | Optional: the notes' git repo. After a pass that changed notes, `pass.py` runs `push.sh`: for plain files it commits the notes' own paths first, and nothing else; then it pushes the current branch, never with force. |
| `branch_shas` | Optional: `{"<repo dir>": "origin/main"}`, for the dashboard's "default branch = <sha>" line. |
| `context_logs` | The other helpers' logs the pass gets the new lines of (comms watcher, MR watch, janitor); missing ones are skipped, `noise` lines left out. |
| `tracker` | Optional: a tracker server and read tools, to check a status or a link. |
| `interval_min`, `model`, `max_usd`, `timeout_s`, `max_log_lines` | 20 minutes, `sonnet`, $3 and 10 minutes per pass, 80 log lines per pass. |
| `push_timeout_s` | 180 seconds for `push.sh`. A slower push is stopped: the pass still ends and moves its cursor, and a notice says so; the commit stays and goes out with the next push. |
| `decision_log`, `evidence_dir`, `timezone`, `deny_servers` | As for the comms watcher. |

## Janitor

Every 10 minutes, with no model, it removes the worktrees under `.worktrees/` whose MR is merged or closed (with the local branch, and the remote branch of a merged MR), and once a day it deletes native build output in worktrees idle for 24 hours. It never touches a dirty worktree, a HEAD that is not the merged or closed MR's head (new commits, or a new task on a reused branch name), a branch without an MR, someone else's MR or the default branch. It reports those in `state/report.log`.

1. Try it: `python3 -I coordination/tools/janitor/janitor.py --self-check` (its tests, on a throwaway repo), then `python3 -I coordination/tools/janitor/janitor.py --once --dry-run`.
2. `coordination/tools/janitor/start.sh` (tmux `janitor`).
3. The coordinator keeps `python3 -I coordination/tools/janitor/janitor.py --wait` running in the background. It returns with the new report lines.

Settings (environment): `JANITOR_AUTHOR` (your GitLab username; by default the user `glab` is logged in as), `JANITOR_CLEAN_HOUR` (default 19; a clean missed because the laptop was asleep runs on the next pass), `JANITOR_BUILD_DIRS` (default `ios/build:android/app/build:android/build:android/.gradle`). It talks to GitLab only. For GitHub, `mrs_for()` would ask `gh pr list --head <branch> --state all` instead.

## Load check

`load.sh` prints a verdict first: GREEN (go), YELLOW (finish the running device job, no new agent, one platform at a time) or RED (pause the device queue, start nothing, close idle agents). Then load per core, swap, free memory, thermal warnings, booted simulators and emulators, the number of worker sessions, the three **biggest agents** by transcript size, and the top CPU processes. Swap alone only ever makes it YELLOW, because macOS keeps swap long after the pressure is gone.

1. `coordination/tools/load-check/start.sh` starts load-watch (tmux `load-watch`): `load.sh` every minute into `state`, verdict changes into `events.log`.
2. The coordinator keeps `coordination/tools/load-check/wait_change.sh` running in the background. It returns when the verdict changes.

Set `LOAD_SKIP_SESSIONS` (a regex, default `janitor|load-watch|mr-watch|comms-watch|scribe`) to the tmux sessions that run no long-lived Claude session, so they don't count as agents. The comms watcher and the scribe run headless passes that keep no transcript.

## Token meter

The plan's weekly token limit is shared by every session. `meter.py` sums the usage of all sessions, subagents and headless passes from the local transcripts (`~/.claude/projects`), weighted to Opus-equivalent by model (`weights` in `budget.json`: Opus 1, Sonnet 0.6, Haiku 0.2; an unknown model counts as 1). The headless helpers keep no transcript, so their `state/runs.log` lines count too.

- `meter.py gate` prints `GREEN | today … | week … | workdays left …`. The week's budget, minus the `reserve`, minus what the week used before today, is spread over the workdays left (today included), so a quiet day leaves more for the next. YELLOW at `day_yellow` of today's share, RED at `day_red` of it or at `week_red` of the whole week.
- `meter.py report [--days n]` is the per-day table with roles and models; `meter.py window "<from>" "<to>"` sums a stretch (for calibration); `meter.py --self-check` tests it on made-up transcripts.
- **`budget.json` starts with placeholders, and the gate refuses to run until they are numbers** (exit code 2, first word `CONFIG`). To calibrate: note the plan's usage percentage at a time, run `meter.py window` from the plan's last reset to then, and the limit is the tokens divided by that fraction. Write how you got it into `calibration`, and set `week_resets` (`weekday` 0 = Monday, `hour`) to the plan's reset. `max_big_workers` caps the live workers on a big model.
- `start.sh` starts token-watch (tmux `token-watch`): the gate every 10 minutes into `state/last`, verdict changes into `state/events.log`. The coordinator keeps `wait_change.sh` running in the background; it returns on each change.
- **`scripts/launch-gated.sh`** takes the arguments of `launch-worker.sh` and refuses (`STOP: …`, exit 3) on RED, on YELLOW for a big model, or when `max_big_workers` workers on a big model already run. Without a verdict from the meter it stops too. `BUDGET_OVERRIDE=1` skips the gate for one launch; set it only when the human said so. A worker counts as a big-model worker unless `--model` names a Sonnet or Haiku model.

The meter reads only token counts and timestamps from the transcripts; it prints no message text.

## e2e runner

`run-flows.sh <device-id> <repo-dir> <flow> [flow …]` runs Maestro flows one at a time and prints one line per flow (PASS or FAIL, seconds, the failing step), then `N/M passed`. The full output stays in `logs/` next to the script for 2 days. An agent reads a log only for a failed flow, so a long run costs a few lines of context instead of thousands. Flows live in `<repo-dir>/e2e/maestro/` unless `FLOWS_DIR` says otherwise. It never signs in.

For another e2e tool, keep the shape: one short line per test, logs on disk, a non-zero exit code when one failed.

## Tracker helper

`md2adf.py <file.md | ->` turns Markdown into Atlassian Document Format (ADF). A tracker that stores ADF (Jira, Confluence) shows `- [ ] item` sent as Markdown as plain text. Sent as ADF, it becomes a real checkbox that QA can tick, and that an agent ticks after merge with the evidence. Use it for tickets with "Acceptance criteria" and "Technical requirements" lists, and for evidence comments. It handles headings, paragraphs, bullet lists, task lists and inline code; anything else stays plain text.

The tracker rules that go with it are under "Tracker" in the `coordinate-workers` skill.
