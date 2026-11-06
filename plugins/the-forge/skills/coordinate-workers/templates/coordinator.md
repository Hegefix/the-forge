# Coordinator rules (read in full at session start)

Only the coordinator reads this file. It sits next to the workspace `CLAUDE.md` (in `coordination/coordinator.md`) instead of inside it, because Claude Code loads `CLAUDE.md` into every turn of every worker and helper, and none of them needs these rules. The skill `the-forge:coordinate-workers` holds the procedures; this file holds what is specific to this workspace.

## Helpers

The helpers this workspace runs, copied from the kit's `templates/tools/` into `coordination/tools/`. Each one works alone; delete the lines you don't use. The skill says how to start, read and stop them.

- **Comms watcher:** `coordination/tools/comms-watch/start-headless.sh`, tmux `comms-watch`, `watcher` profile. Sources, key conversations and schedule: its `config.json`. It runs only in the working hours below.
- **MR watch:** `coordination/tools/mr-watch/start.sh`, tmux `mr-watch`, a script.
- **Scribe, optional,** only with a knowledge base: `coordination/tools/scribe/start-headless.sh`, tmux `scribe`, `watcher` profile.
- **Janitor:** `coordination/tools/janitor/start.sh`, tmux `janitor`, a script.
- **Load watch:** `coordination/tools/load-check/start.sh`, tmux `load-watch`, a script.
- **Token meter:** `coordination/tools/token-meter/start.sh`, tmux `token-watch`, a script. Workers start through `launch-gated.sh`.
- **e2e runner:** `coordination/tools/e2e/run-flows.sh <device> <repo> <flow …>`.
- **Tracker helper:** `coordination/tools/tracker/md2adf.py`, run by hand.

## Models per role

| Role | Model | How |
|---|---|---|
| Coordinator, planning and review agents, workers on feature code | the strongest model | the session default |
| Mechanical workers: merges of the default branch, review-comment fixes, e2e re-runs, QA builds, evidence uploads | a smaller model (`sonnet`) | `launch-gated.sh --model sonnet …` |
| Self-review lens subagents | a smaller model | `model: "sonnet"` in each Agent call |
| Tracker clerk (batch of tracker reads and writes) | a small model (`haiku`) | `model: "haiku"` in the Agent call |
| Scribe, comms watcher | a mid-size model | `model` in their `config.json` (a small one skipped threads and whole conversations) |
| MR watch, load check, janitor, token meter | none | scripts |

A new helper gets the smallest model that does its job. Moving any other role to a smaller model is the human's call.

## Token budget

The plan has a weekly limit. The token meter (`coordination/tools/token-meter/`) sums usage from the local transcripts, weighted to Opus-equivalent, and `meter.py gate` says GREEN, YELLOW or RED against `budget.json`.

- Put the gate line in every status to the human.
- Start workers only through `launch-gated.sh`. GREEN: any model, at most <3> workers on a big model alive. YELLOW: a smaller model only. RED: nothing new; running workers finish their step and checkpoint. `BUDGET_OVERRIDE=1` only on the human's word, for that one launch.
- Keep `coordination/tools/token-meter/wait_change.sh` armed; act on each verdict change.
- Close an agent at its deliverable or at ~10 MB of transcript. Ask the human for a `/compact` or a handover at ~150k tokens of your own context.
- Big jobs (overnight research, many agents, whole-repo sweeps) need the human's OK with a token estimate, run on a smaller model, and go late in the week, when the unused budget would expire anyway.

## Chat and helper hours

- **Chat writes** (channel posts, thread replies, DMs) go out only in the "Chat hours" setting of the workspace `CLAUDE.md`. Outside them, an approved message waits for the next window, or goes as a scheduled message for that time with the human's OK on the text. Reading chat is fine at any time.
- **The comms watcher** runs only in the working hours (`schedule` in its `config.json`, `otherwise_every_min: 0`). Its first pass of the day reads everything since its cursor.

## Native builds

A native build (prebuild, xcodebuild, Gradle, `expo run`) is device work: a worker builds only after your "go". At most <2> builds at once, and the second starts only on a GREEN load (or a YELLOW from swap alone). Local Android builds are for one ABI.

## Standing rules

Actions <name> has pre-approved. From the date of approval they are class A or B and don't go to the human. Add approved rule proposals here, with the date. Rules that also bind workers go into the workspace `CLAUDE.md` under "Shared rules".

- <yyyy-mm-dd> <rule>

The skills already carry the kit's delivery defaults: one MR per feature, short MR descriptions, Draft without reviewers, the human's check, the Risk score, the worker's self-review, e2e scope, one deliverable per agent and a retrospective per feature. Add a rule here to change a default or to pre-approve an action. Examples to keep, adapt or delete:

- **Review-comment replies** that only say what was changed or answer a factual question: the coordinator sends them. Disagreeing with a reviewer is D. Threads, fixes and re-asks follow the skill `review-loop`.
- **Reviews where <name> is a reviewer:** as soon as <name> is added as a reviewer on someone else's MR, the coordinator starts a `research` worker on it without being asked, and again when new commits land after their review (skill `review-round`). <name> gets one line: the verdict and a ready comment. The coordinator posts it or approves only after their OK for that MR.
- **Review requests:** post `<@reviewer> - <what> - <MR link>` in <channel or thread>. Default reviewers: <names or handles>.
- **Ticket status:** a ticket goes to <In Progress>, and is assigned to <name>, the moment work starts; to <QA status> once merged.
- **QA builds:** built from the default branch on <days>, when it has something new for QA. Each build is a new top-level message in <channel>, tagging <QA person>: the build and commit, the tickets in it, known issues. The coordinator sends it with the build attached, without asking (skill `qa-handoff`).
- **QA results:** a pass goes to <done status>, moved by the coordinator without asking; a fail gets a comment (build, steps, screenshot or video) and goes back to <In Progress>; something new gets its own bug.
- **QA evidence:** for every merged UI ticket, record videos on the default branch, attach them to the ticket, post the evidence comment (acceptance criteria table with `file:line`) and a "How to test" comment (3–6 steps, the account to use, what's out of scope), and move it to <QA status>.
- **Merging our own MRs:** the coordinator merges once the MR has a reviewer's approval, green CI and green e2e. Stacked MRs merge in the order the coordinator set. Several approved MRs land as a merge train, one at a time with a head-SHA guard (skill `merge-train`). Releases, production deploys and MRs in repos other teams own stay D.

## Shared scarce resources

Delete this section if you have none.

- <resource, e.g. "iOS simulator">: at most <n> in use at a time. You hand it out; a worker uses it only after "go" and releases it when done. <Why, e.g. "the laptop overheats">.
