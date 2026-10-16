# <workspace name>: coordinator workspace

This folder is not a repo. It holds the repos I work on, agent worktrees (`.worktrees/<repo>/<task>`) and the coordination files (`coordination/`). Claude sessions here play one of three roles, depending on where they run:

- **Coordinator:** a session whose cwd is exactly this folder. Use the skill `the-forge:coordinate-workers`.
- **Worker:** a session whose cwd is anywhere below it, usually `.worktrees/<repo>/<task>`. Use the skill `the-forge:work-for-coordinator`. The repo's own `CLAUDE.md` applies too, and wins on repo matters.
- **Helper:** a session in `coordination/tools/<helper>/` that runs its own instructions file on a loop (`WATCH.md`, `SCRIBE.md`). It follows that file, not the two skills.

## Coordination settings

- **The human:** <name>. Answer in <language>, <tone, e.g. "short and plain">.
- **Coordinator session:** `<session name>`. It stays the same across coordinator sessions, because worker briefs and helpers address it.
- **Handover note:** `coordination/handover.md`
- **Decision log:** `coordination/decision-log.md`
- **Dashboard:** <path to a task or sprint overview, or "none">
- **Knowledge base:** none: the handover note, the dashboard and notes are plain files in `coordination/`. <Or, if you keep an LLM wiki: "<notes MCP server, e.g. an Obsidian vault>, folder <folder>": the handover note, the dashboard and the notes live there, and the scribe may keep them.>
- **Evidence folder:** `.evidence/<task>/`: MR description drafts, walkthroughs, screenshots, test results. A fresh agent starts from here.
- **Working hours** (helpers skip passes outside them): <e.g. Mon–Fri 08:30–18:30, local time>
- **Worker permission mode:** <default | acceptEdits | auto>
- **Worker permission profiles:** `coordination/permission-profiles/` (`research`, `code`, `device`, `watcher`)
- **Agent names:** neutral, `<repo>-<task>`. <Or your own scheme, such as themed names. Names stay internal.>
- **Repos:** <path> (<remote>, default branch <name>), one line each.

## Helpers

Scripts and loop sessions that save the coordinator work. Copied from the kit's `templates/tools/` into `coordination/tools/`. Each one works alone; delete the ones you don't use. The coordinator starts them on workdays and stops them at the end of the day with `tmux kill-session -t <name>`, directly: a delayed kill (`sleep 1500; tmux kill-session …`) doesn't survive a laptop sleep and fires the next morning.

- **Comms watcher** (`coordination/tools/comms-watch/start.sh`, tmux `comms-watch`, `watcher` profile): a read-only session on a small model that sends the coordinator one digest every 10 minutes from chat, git hosting and the tracker, each item labelled `human`, `judgment`, `mechanical` or `fyi`. The coordinator acts on the digests instead of reading the feeds, and checks the source before replying to anyone. Its sources are in "Comms watcher sources" below.
- **MR watch** (`coordination/tools/mr-watch/start.sh`, tmux `mr-watch`, a script, no model): every 90 seconds it checks the human's open MRs and appends one line per change (approval, new comment, pipeline result, merge) to `events.log`. Keep `python3 -I coordination/tools/mr-watch/wait_event.py` running in the background, act on each line, and start it again.
- **Scribe, optional** (`coordination/tools/scribe/start.sh`, tmux `scribe`, `watcher` profile): only if you keep a knowledge base (an LLM wiki, such as an Obsidian vault behind an MCP server). Every 20 minutes it rewrites the dashboard, the handover note's "State" and the knowledge notes from the decision log. For a conclusion that isn't in the log, send the scribe `save: <conclusion>`. Without a scribe, the coordinator refreshes the handover note's "State" itself at the end of each stage. Either way, keep the decision log complete and specific (results, root causes, SHAs, `file:line`), and before a handover check that the handover note is current.
- **Janitor** (`coordination/tools/janitor/start.sh`, tmux `janitor`, a script, no model): every 10 minutes it removes the worktrees of merged or closed MRs, with their local branch and a merged MR's remote branch. Once a day it deletes native build output in worktrees idle for 24 hours. It never touches a dirty worktree, unpushed commits, a branch without an MR, or the default branch; it reports those. Keep `python3 -I coordination/tools/janitor/janitor.py --wait` running in the background, read its report, and decide what it left.
- **Load watch** (`coordination/tools/load-check/start.sh`, tmux `load-watch`, a script): runs `load.sh` every minute. Keep `coordination/tools/load-check/wait_change.sh` running in the background to hear when the verdict changes.
- **Tracker helper** (`coordination/tools/tracker/md2adf.py`, run by hand): turns Markdown into the tracker's document format, so `- [ ]` lists become real checkboxes.

### Models per role

| Role | Model |
|---|---|
| Coordinator, planning and review agents, workers on feature code | the strongest model (the session default) |
| Scribe | a mid-size model (`sonnet`, `SCRIBE_MODEL`) |
| Comms watcher | a small model (`haiku`, `COMMS_WATCH_MODEL`) |
| MR watch, load check, janitor | none (scripts) |

A new loop helper gets the smallest model that does its job. Moving any other role to a smaller model is the human's call.

### Comms watcher sources

Delete this section if you don't run the comms watcher.

- **The human:** chat <user id>, git hosting `<username>`, tracker <display name>.
- **Channels:** <channel name> (<id>): top-level messages, plus replies in threads where the human posted or was mentioned. One line each.
- **Direct messages:** all DMs and group DMs to the human, by search (Slack: `after:<yesterday>`, `channel_types: "im,mpim"`). Backup, read each one directly: <person> (<user id>), one per line.
- **Git hosting:** the human's open MRs or PRs in every project: <query, e.g. `glab api "merge_requests?author_username=<username>&state=opened&scope=all"`>.
- **Tracker:** <query, e.g. `project = <KEY> AND labels = <label> AND updated >= -<minutes>m`>.

## Standing rules

Actions <name> has pre-approved. From the date of approval they are class A or B and don't go to the human. The coordinator adds approved rule proposals here.

- <yyyy-mm-dd> <rule>

Examples to keep, adapt or delete:

- **Review-comment replies** that only say what was changed or answer a factual question: the coordinator sends them. Disagreeing with a reviewer is D.
- **Direct messages go by user ID.** Send a DM to the person's user ID, or read the DM channel first and check who is in it. Never take a channel ID from a log or a digest: one mislabelled line sends the message to the wrong person, and chat tools often can't delete it.
- **Review requests:** post `<@reviewer> - <what> - <MR link>` in <channel or thread>. Default reviewers: <names or handles>.
- **Draft → ready only after <name>'s own check.** Once CI, the full e2e suite and the screenshots are in, the coordinator sends <name> one "ready for your check" line: the MR link, what to try on the device, what changed. With it comes the worker's one-page walkthrough, `.evidence/<task>/walkthrough.md`: how it works, the data flow, the 5–10 key files and what to read in each, the tricky parts, the decisions. <name> reads it with the code, so they can answer any reviewer question themselves. Only after their OK for that MR: out of Draft, reviewers set, review request posted.
- **A Draft MR has no reviewers.** Set them only when it leaves Draft, and clear them when an MR goes back to Draft.
- **Short MR descriptions.** The part a reviewer sees is at most ~15 lines: the Risk line (plus the "Hand-tested…" or "No review needed…" line), what changed in 3–5 bullets, why with the ticket link, how it was checked in 1–2 lines, and for UI changes a screenshot table (iOS and Android, or your platforms). Everything else (decisions, full test lists, notes) goes into one collapsed `<details><summary>Details</summary>…</details>` block or the walkthrough. Every name, count and "no X needed" claim must match the diff.
- **Screenshots in the MR for UI changes,** before it leaves Draft. Uploads usually can't be deleted, so capture a test account or test content only, with no personal data. Videos go to the ticket.
- **Show the human's check.** When an MR leaves Draft, its description gets the line "Hand-tested and code reviewed by <name> (<date>)." under the Risk line, and the MR gets the label `ai:generated`. Write the line only when both are true.
- **`no-review-needed`:** our MRs with Risk 0–1 (CI, docs, tests, e2e flows, renames without new logic) get the label `no-review-needed` and the line "No review needed: <why>, a quick approve is enough." under the Risk line. Their review request says "quick approve". Risk 2 and up gets a normal review.
- **One MR per feature.** Plan tickets at feature size, one MR each. Use sub-tasks only when the work is really split between parallel workers, then one MR per sub-task. Never split a ticket's work over several MRs on your own; if it's too big, propose the split as D.
- **Tickets: acceptance criteria apart from technical requirements.** "Acceptance criteria" are user-facing only: what manual QA can check on a build. "Technical requirements" are the rest: e2e flows, CI, screenshots, evidence. Technical requirements are ticked after merge, from the pipeline and the evidence, automatically where possible. QA gets a short "How to test" for the acceptance criteria.
- **Ticket status:** a ticket goes to <In Progress>, and is assigned to <name>, the moment work starts; to <QA status> once merged. Look transitions up by the target status name, never by a hard-coded id: ids differ per issue type.
- **Sprint or backlog:** a ticket for work that starts now goes into the active sprint. Planned work (a milestone's tickets, a follow-up for later) goes to the backlog, and enters a sprint at planning or when work starts.
- **QA builds:** built from the default branch on <days>, when it has something new for QA. Each build is a new top-level message in <channel>, tagging <QA person>: the build and commit, the tickets in it, known issues.
- **QA evidence:** for every merged UI ticket, record videos on the default branch, attach them to the ticket, post the evidence comment (acceptance criteria table with `file:line`) and a "How to test" comment (3–6 steps, the account to use, what's out of scope), and move it to <QA status>.
- **How much e2e to run.** The full e2e suite runs once per MR, on every platform, before <name>'s check. After that (a merge of the default branch, a review fix, a small change), run only the flows that touch the changed or conflicted areas, plus `smoke`, and say which. A suite for signed-out flows runs only when sign-in or app start changed. A QA build gets `smoke` plus the flows of the tickets in it. "Green e2e" in the merge rule means this. Run flows with `coordination/tools/e2e/run-flows.sh <device> <repo> <flow …>`: one line per flow, logs on disk, and an agent reads a log only for a failed flow.
- **One deliverable per agent.** Every turn of a long-lived agent re-reads its whole context, so a big context costs on every turn. Close an agent when its MR is merged or handed over, or when it's idle with a transcript over ~30 MB. The next step goes to a fresh agent that starts from `.evidence/<task>/` (MR description, walkthrough). Look at the "biggest agents" line of `coordination/tools/load-check/load.sh` at every status.
- **Merging our own MRs:** the coordinator merges once the MR has a reviewer's approval, green CI and green e2e. Stacked MRs merge in the order the coordinator set. Releases, production deploys and MRs in repos other teams own stay D.

## Shared scarce resources

Delete this section if you have none.

- <resource, e.g. "iOS simulator">: at most <n> in use at a time. The coordinator hands it out; a worker uses it only after "go" and releases it when done. <Why, e.g. "the laptop overheats">.
- **Load check:** before handing the devices to the next agent or starting a new agent, the coordinator runs `coordination/tools/load-check/load.sh`. GREEN: go. YELLOW: let the running device job finish, start no new agent, one platform at a time. RED: pause the device queue, start nothing, close idle agents, check again in a few minutes.

## Repo rules

House rules that the coordinator relays to workers and checks in review, for repos whose own `CLAUDE.md` doesn't state them.

- <repo>: <rule>
- <repo>: module boundaries are enforced by lint (optional; see the kit's `templates/examples/module-boundaries/`): another module only through its index, and no module imports a page-level module.
