# Coordinator handover

Live handover for the coordinator session in `<workspace path>`, so that a fresh session can take over when this one's context gets too large. "State" is rewritten at the end of each stage: by the scribe if one runs, from the decision log, otherwise by the coordinator. The rest changes rarely.

Last updated: **<yyyy-mm-dd hh:mm>**, by coordinator `<session name>`.

## Takeover in 6 steps

1. Start the new session in the workspace root (cwd exactly that folder = coordinator role).
   - If the old session is gone, reuse its name: `claude --name <session name>`. Worker briefs name the coordinator, so their messages reach you without changes.
   - If both are alive, pick a new name and tell every live worker: "coordinator is now `<name>`".
2. Read, in this order: the workspace `CLAUDE.md` (settings, standing rules); this note; the dashboard, if there is one; the last ~40 lines of the decision log.
3. Run `ListAgents` and `tmux ls`, and compare them with "Live workers" and "Helpers" below. To read a worker's screen without interrupting it: `tmux capture-pane -t <session> -p | tail -40`.
4. On a workday, start the helpers that aren't running, and arm the background waiters (`janitor.py --wait`, `wait_change.sh`). Run `load.sh` once.
5. Check what changed since "Last updated": the places under "Watch", and open MRs.
6. Tell <the human> in one line: "took over, open: …".

## Working with <the human>

- Language and tone: <…>.
- They answer escalations by id ("D-3 ok, D-4 alt"). The next free id is **D-1**.
- Message them only for a BLOCKING D item, while they are actively testing, when an MR is ready for their check, or when a stage finished.
- <Anything else the next coordinator must know about how they work: what they always check themselves, what they never want touched.>

## State (rewrite at each stage)

**Done since the last stage**

- <…>

**In flight**

1. <task> (<worker>): <state> — next: <step> — waiting on <what/who>

**Open D items, waiting on <the human>**

- D-<n>: <one line>. Recommendation: <…>. Default: <…> | BLOCKING.

**Waiting on others**

- <person or team>: <what>

**Live workers**

| name | tmux session | worktree | branch / MR | profile | transcript | state |
|---|---|---|---|---|---|---|
| <worker-name> | <repo>--<task> | `.worktrees/<repo>/<task>` | <branch>, <MR> | research / code / device | <n> MB | idle / busy / holds <resource> |

One deliverable per worker: close it when its MR merges or is handed over, or when it's idle with a transcript over ~30 MB, and log it. The janitor removes merged worktrees and branches.

**Helpers:** <comms-watch, mr-watch, janitor, load-watch, scribe (optional): running | stopped | not used>. Last janitor report: <time, what it left for a decision>.

**Scarce resources:** <resource> held by <worker> since <time> | all free.

## Watch

Places to check for news on takeover: <channels, threads, MR lists, dashboards>.

## Where things are

- Repos: `<path>` (<remote>), one line each.
- Worktrees: `.worktrees/<repo>/<task>`.
- Decision log: `<path>`. Worker briefs: `<path>`.
- How-tos and research notes: <paths or links>.

## Gotchas

Things learned the hard way, one line each. A few from earlier workspaces, to keep or delete:

- Stop helpers with a direct `tmux kill-session`. A delayed kill (`sleep 1500 && tmux kill-session …`) survives a laptop sleep and fires the next morning, killing that day's helper.
- Slack's search filter `after:<date>` excludes that day: `after:<today>` returns nothing. Search from yesterday, then filter by time.
- A stacked MR merged into another feature branch is not merged to the default branch. Check `target_branch` before you report "merged".
- A settings file with a `//` comment is ignored without an error, and then the profile blocks nothing. Keep profiles strict JSON.
- A DM sent to a channel ID taken from a log line went to the wrong person, because the log had mislabelled it. Send to the user ID, or read the channel first and check who is in it.
- Tracker transition ids differ per issue type: the id for "In Review" on one type was "Blocked" on another. Look transitions up by the target status name.
- <…>
