You are worker "<worker-name>" (`research` profile: read only). Coordinator: "<coordinator-name>" (SendMessage). Load the skill `the-forge:work-for-coordinator` and follow it.

Task: a short retrospective of <feature: ticket or epic key, title>, whose last MR merged on <date>. You write nothing and post nothing: send the retro to me by message, and I save it as `.evidence/<feature>/retro.md`. Use only what the sources show: `glab api` is denied, so read MRs with `glab mr view <n> -R <group/repo> --comments --system-logs` (`-F json` for exact times) and pipelines with `glab ci list` and `glab ci get`. Write `n/a` for what they can't show; never estimate.

Sources, read only:
- Plan: <`.evidence/<feature>/plan.md` | the ticket or epic description>.
- Tickets: <keys>, with their evidence comments (the acceptance-criteria sign-off).
- MRs: <repo !n, one per line>: discussions, pipelines, timestamps.
- Evidence folders: <`.evidence/<task>/`, one per task>: walkthroughs, test results with the e2e runner's times, `deferred.md` (skip lines already marked ` → <key>` or ` → rejected`).
- Decision log: <path>: the lines that name these tickets or MRs, D items <D-x … D-y>, and the `[rule]` and `RULE PROPOSAL` lines.
- Standing rules: the workspace `CLAUDE.md`.

Send at most ~50 lines, in this shape:

    # Retro: <feature>

    ## Plan vs shipped
    - <planned item> — shipped | changed: <how> | dropped: <why>
    - Not planned, shipped: <item> — <why it came in>

    ## Acceptance criteria
    - <criterion> — ✅ | ⚠️ | ❌ | ➖ | QA pending — <evidence: file:line, e2e flow or ticket comment>

    ## Ticket drafts from deferred work
    - <type>: <title> — <what and why, 1–2 lines> — from <file:line | thread link>
    Merged duplicates: <n>. Dropped as already fixed or ticketed: <line → commit or key>.

    ## Rule proposals
    - [RULE PROPOSAL] <rule> — based on D-x, D-y
    (only questions the human answered the same way two or more times, and not already a standing rule or proposed before)

    ## What was slow
    - Per MR: days from the first commit to Draft, from Draft to the human's OK, from the OK to merge; review rounds; pipelines failed of total, and the slowest job; e2e time from the runner's lines.
    - The 1–2 main causes, and the one change that would have saved the most time.

Then stop.
