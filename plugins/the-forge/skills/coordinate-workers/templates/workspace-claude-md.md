# <workspace name>: coordinator workspace

This folder is not a repo. It holds the repos I work on, agent worktrees (`.worktrees/<repo>/<task>`) and the coordination files (`coordination/`). Claude sessions here play one of three roles, depending on where they run:

- **Coordinator:** a session whose cwd is exactly this folder. **Before anything else, read `coordination/coordinator.md` in full** (the helpers it runs, models per role, the token budget, chat hours, standing rules). It lives outside this file because this file loads into every turn of every worker and helper. Use the skill `the-forge:coordinate-workers`.
- **Worker:** a session whose cwd is anywhere below it, usually `.worktrees/<repo>/<task>`. Use the skill `the-forge:work-for-coordinator`. The repo's own `CLAUDE.md` applies too, and wins on repo matters.
- **Helper:** a headless `claude -p` pass that a helper's shell loop in `coordination/tools/<helper>/` starts (the comms watcher, the scribe). It follows its own `PASS.md`, not the two skills, and doesn't load this file.

## Coordination settings

- **The human:** <name>. Answer in <language>, <tone, e.g. "short and plain">.
- **Coordinator session:** `<session name>`. It stays the same across coordinator sessions, because worker briefs and helpers address it.
- **Handover note:** `coordination/handover.md`
- **Decision log:** `coordination/decision-log.md`
- **Dashboard:** <path to a task or sprint overview, or "none">
- **Knowledge base:** none: the handover note, the dashboard and notes are plain files in `coordination/`. <Or, if you keep an LLM wiki: "<notes MCP server, e.g. an Obsidian vault>, folder <folder>": the handover note, the dashboard and the notes live there, and the scribe may keep them.>
- **Evidence folder:** `.evidence/<task>/`: MR description drafts, walkthroughs, screenshots, test results, `deferred.md` (work outside the task). A fresh agent starts from here. A feature's retrospective goes to `.evidence/<feature>/retro.md`.
- **Working hours:** <e.g. Mon–Fri 09:00–18:00, local time>. The comms watcher runs only in them: its `schedule` in `config.json` follows them, and its first pass of the day reads everything since its cursor.
- **Chat hours:** <e.g. the same as the working hours>. Chat writes go out only then; outside them an approved message waits or is scheduled. Reading is fine at any time.
- **Token budget:** <none | the token meter is set up in `coordination/tools/token-meter/`; at most <3> workers on a big model>. Workers start through `launch-gated.sh`.
- **Worker permission mode:** <default | acceptEdits | auto>
- **Worker permission profiles:** `coordination/permission-profiles/` (`research`, `code`, `device`, `browser`, `watcher`)
- **Agent names:** neutral, `<repo>-<task>`. <Or your own scheme, such as themed names. Names stay internal.>
- **Repos:** <path> (<remote>, default branch <name>), one line each.

## Shared rules

Rules that bind workers too, so they live here and not in `coordination/coordinator.md`. Add a rule when the human approves it for everyone. Examples to keep, adapt or delete:

- **Every MR gets <the human> as assignee,** Draft or not. Reviewers and taking it out of Draft stay with the coordinator.
- **No manual QA where it adds nothing:** tickets with no user-visible change, and small UI fixes fully covered by e2e and MR screenshots, get the label `no-manual-qa`. They never enter the QA column, and after merge the developer posts a "Verified by dev" comment with the evidence (skill `coordinate-workers`, "Escalating to the human").
- **Screenshots in the MR for UI changes,** before it leaves Draft. Uploads usually can't be deleted, so capture a test account or test content only, with no personal data. Videos go to the ticket.
- **Performance check for UI MRs:** before the "ready for your check" line, the worker measures FPS, CPU and RAM on the touched screens, on a release build and the same device, the branch against the default branch. A drop over <10>% FPS or a rise over <15>% CPU holds the line until it's explained or fixed.
- **e2e for a QA build:** `smoke` plus the flows of the tickets in it. "Green e2e" in the merge rule means the e2e scope in `work-for-coordinator`.
- **Native builds are device work:** only after the coordinator's "go", at most <2> at once, and local Android builds for one ABI.
- **Token budget:** read files in parts, keep command output short, save screenshots to files and open only one or two, and report to the coordinator only at milestones.
- **Nothing other people see** carries agent names, ranks, decision ids or the kit's wording: not chat, commits, MR descriptions, tickets or mail.

The coordinator's own rules (the helpers it runs, models per role, the token budget gate, chat hours, standing rules, scarce resources) are in `coordination/coordinator.md`.

## Repo rules

House rules that the coordinator relays to workers and checks in review, for repos whose own `CLAUDE.md` doesn't state them.

- <repo>: <rule>
- <repo>: module boundaries are enforced by lint (optional; see the kit's `templates/examples/module-boundaries/`): another module only through its index, and no module imports a page-level module.
