# <workspace name>: coordinator workspace

This folder is not a repo. It holds the repos I work on, agent worktrees (`.worktrees/<repo>/<task>`) and the coordination files (`coordination/`). Claude sessions here play one of three roles, depending on where they run:

- **Coordinator:** a session whose cwd is exactly this folder. Use the skill `the-forge:coordinate-workers`.
- **Worker:** a session whose cwd is anywhere below it, usually `.worktrees/<repo>/<task>`. Use the skill `the-forge:work-for-coordinator`. The repo's own `CLAUDE.md` applies too, and wins on repo matters.
- **Helper:** a headless `claude -p` pass that a helper's shell loop in `coordination/tools/<helper>/` starts (the comms watcher, the scribe). It follows its own `PASS.md`, not the two skills, and doesn't load this file.

## Coordination settings

- **The human:** <name>. Answer in <language>, <tone, e.g. "short and plain">.
- **Coordinator session:** `<session name>`. It stays the same across coordinator sessions, because worker briefs and helpers address it.
- **Handover note:** `coordination/handover.md`
- **Decision log:** `coordination/decision-log.md`
- **Dashboard:** <path to a task or sprint overview, or "none">
- **Knowledge base:** none: the handover note, the dashboard and notes are plain files in `coordination/`. <Or, if you keep an LLM wiki: "<notes MCP server, e.g. an Obsidian vault>, folder <folder>": the handover note, the dashboard and the notes live there, and the scribe may keep them.>
- **Evidence folder:** `.evidence/<task>/`: MR description drafts, walkthroughs, screenshots, test results. A fresh agent starts from here.
- **Working hours:** <e.g. Mon–Fri 08:30–18:30, local time>. The comms watcher's schedule in its `config.json` follows them.
- **Worker permission mode:** <default | acceptEdits | auto>
- **Worker permission profiles:** `coordination/permission-profiles/` (`research`, `code`, `device`, `browser`, `watcher`)
- **Agent names:** neutral, `<repo>-<task>`. <Or your own scheme, such as themed names. Names stay internal.>
- **Repos:** <path> (<remote>, default branch <name>), one line each.

## Helpers

Scripts that save the coordinator work; the comms watcher and the scribe run one headless Claude pass at a time. Copied from the kit's `templates/tools/` into `coordination/tools/`. Each one works alone; delete the ones you don't use. The coordinator starts them on workdays and stops them at the end of the day with `tmux kill-session -t <name>`, directly: a delayed kill (`sleep 1500; tmux kill-session …`) doesn't survive a laptop sleep and fires the next morning.

- **Comms watcher** (`coordination/tools/comms-watch/start-headless.sh`, tmux `comms-watch`, `watcher` profile): a shell loop that runs one read-only headless `claude -p` pass per interval (every 7 minutes in workday hours by default). A pass reads what's new in chat, the tracker, mail and the git hosting to-dos, and writes one digest file with news to `state/digests/`, each item labelled `human`, `judgment`, `mechanical` or `fyi`. Its sources, key conversations and schedule are in its `config.json`. Keep ONE waiter running in the background for it and the scribe: `python3 -I coordination/tools/comms-watch/wait_digest.py coordination/tools/comms-watch/state/digests coordination/tools/scribe/state/notices`. The coordinator acts on the digests instead of reading the feeds, and checks the source before replying to anyone.
- **MR watch** (`coordination/tools/mr-watch/start.sh`, tmux `mr-watch`, a script, no model): every 90 seconds it checks the human's open MRs and appends one line per change (approval, new comment, pipeline result, merge) to `events.log`. Keep `python3 -I coordination/tools/mr-watch/wait_event.py` running in the background, act on each line, and start it again.
- **Scribe, optional** (`coordination/tools/scribe/start-headless.sh`, tmux `scribe`, `watcher` profile): only if you keep a knowledge base (an LLM wiki, such as an Obsidian vault behind an MCP server, or a notes folder). Every 20 minutes a gate with no model checks the decision log and its inbox; only when one has something new does a headless pass rewrite the dashboard, the handover note's "State" and the knowledge notes. For a conclusion that isn't in the log, run `coordination/tools/scribe/save.sh "<conclusion>"`. Its rare notices come through the waiter above. Without a scribe, the coordinator refreshes the handover note's "State" itself at the end of each stage. Either way, keep the decision log complete and specific (results, root causes, SHAs, `file:line`), and before a handover check that the handover note is current.
- **Janitor** (`coordination/tools/janitor/start.sh`, tmux `janitor`, a script, no model): every 10 minutes it removes the worktrees of merged or closed MRs, with their local branch and a merged MR's remote branch. Once a day it deletes native build output in worktrees idle for 24 hours. It never touches a dirty worktree, a HEAD that is not the merged or closed MR's head (new commits, or a new task on a reused branch name), a branch without an MR, or the default branch; it reports those. Keep `python3 -I coordination/tools/janitor/janitor.py --wait` running in the background, read its report, and decide what it left.
- **Load watch** (`coordination/tools/load-check/start.sh`, tmux `load-watch`, a script): runs `load.sh` every minute. Keep `coordination/tools/load-check/wait_change.sh` running in the background to hear when the verdict changes.
- **Tracker helper** (`coordination/tools/tracker/md2adf.py`, run by hand): turns Markdown into the tracker's document format, so `- [ ]` lists become real checkboxes.

### Models per role

| Role | Model |
|---|---|
| Coordinator, planning and review agents, workers on feature code | the strongest model (the session default) |
| Scribe | a mid-size model (`sonnet`, `model` in its `config.json`) |
| Comms watcher | a mid-size model (`sonnet`, `model` in its `config.json`); a small model skipped threads and whole conversations |
| MR watch, load check, janitor | none (scripts) |

A new helper gets the smallest model that does its job. Moving any other role to a smaller model is the human's call.

## Standing rules

Actions <name> has pre-approved. From the date of approval they are class A or B and don't go to the human. The coordinator adds approved rule proposals here.

- <yyyy-mm-dd> <rule>

Examples to keep, adapt or delete:

- **Review-comment replies** that only say what was changed or answer a factual question: the coordinator sends them. Disagreeing with a reviewer is D. Threads, fixes and re-asks follow the skill `review-loop`.
- **Reviews where <name> is a reviewer:** as soon as <name> is added as a reviewer on someone else's MR, the coordinator starts a `research` worker on it without being asked, and again when new commits land after their review (skill `review-round`). <name> gets one line: the verdict and a ready comment. The coordinator posts it or approves only after their OK for that MR.
- **Browser work goes to a browser worker:** developer portals, store consoles, CI web pages and uploads go to one worker with the `browser` profile and a brief that names the sites and the exact actions (skill `browser-worker`). The coordinator never drives the browser itself. <name> signs in.
- **One chat message, not five:** if every chat send asks <name> for an approval click (an organization policy on the chat connector), review requests and notes go out as one message, a line per item.
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
- **QA builds:** built from the default branch on <days>, when it has something new for QA. Each build is a new top-level message in <channel>, tagging <QA person>: the build and commit, the tickets in it, known issues. The coordinator sends it with the build attached, without asking (skill `qa-handoff`).
- **QA results:** a pass goes to <done status>, moved by the coordinator without asking; a fail gets a comment (build, steps, screenshot or video) and goes back to <In Progress>; something new gets its own bug.
- **QA evidence:** for every merged UI ticket, record videos on the default branch, attach them to the ticket, post the evidence comment (acceptance criteria table with `file:line`) and a "How to test" comment (3–6 steps, the account to use, what's out of scope), and move it to <QA status>.
- **How much e2e to run.** The full e2e suite runs once per MR, on every platform, before <name>'s check. After that (a merge of the default branch, a review fix, a small change), run only the flows that touch the changed or conflicted areas, plus `smoke`, and say which. A suite for signed-out flows runs only when sign-in or app start changed. A QA build gets `smoke` plus the flows of the tickets in it. "Green e2e" in the merge rule means this. Run flows with `coordination/tools/e2e/run-flows.sh <device> <repo> <flow …>`: one line per flow, logs on disk, and an agent reads a log only for a failed flow.
- **One deliverable per agent.** Every turn of a long-lived agent re-reads its whole context, so a big context costs on every turn. Close an agent when its MR is merged or handed over, or when it's idle with a transcript over ~30 MB. The next step goes to a fresh agent that starts from `.evidence/<task>/` (MR description, walkthrough). Look at the "biggest agents" line of `coordination/tools/load-check/load.sh` at every status.
- **Performance check for UI MRs:** before the "ready for your check" line, the worker measures FPS, CPU and RAM on the touched screens, on a release build and the same device, the branch against the default branch. A drop over <10>% FPS or a rise over <15>% CPU holds the line until it's explained or fixed.
- **Merging our own MRs:** the coordinator merges once the MR has a reviewer's approval, green CI and green e2e. Stacked MRs merge in the order the coordinator set. Several approved MRs land as a merge train, one at a time with a head-SHA guard (skill `merge-train`). Releases, production deploys and MRs in repos other teams own stay D.

## Shared scarce resources

Delete this section if you have none.

- <resource, e.g. "iOS simulator">: at most <n> in use at a time. The coordinator hands it out; a worker uses it only after "go" and releases it when done. <Why, e.g. "the laptop overheats">.
- **Load check:** before handing the devices to the next agent or starting a new agent, the coordinator runs `coordination/tools/load-check/load.sh`. GREEN: go. YELLOW: let the running device job finish, start no new agent, one platform at a time. RED: pause the device queue, start nothing, close idle agents, check again in a few minutes.

## Repo rules

House rules that the coordinator relays to workers and checks in review, for repos whose own `CLAUDE.md` doesn't state them.

- <repo>: <rule>
- <repo>: module boundaries are enforced by lint (optional; see the kit's `templates/examples/module-boundaries/`): another module only through its index, and no module imports a page-level module.
