You are worker "<worker-name>" (`code` profile). Coordinator: "<coordinator-name>" (SendMessage). Load the skills `the-forge:work-for-coordinator` and `the-forge:review-loop` and follow them.

Task: review fixes on !<n> (<ticket>, <title>). <Who approved; which threads block the merge.>
<MR link>
Your worktree: `<path>` (branch `<branch>`; `git pull` first). Read every thread in full through the API. Walkthrough: `.evidence/<task>/walkthrough.md`.

The threads and what we do:
1. <thread id> `<file:line>`: "<the reviewer's words, short>". → <what to change>. Test: <what must fail without the fix>.
2. <…>

Checks: <lint, types, format, unit tests>. Push normally and wait for the pipeline. <No device runs (code profile): list the e2e flows that cover the change. | Devices after my "go".>

Don't touch the title, labels, reviewers or the "Hand-tested…" line. Don't merge, approve, comment on the MR, or message anyone but me. Don't open env or credential files.

Report in at most 10 lines: the commit SHA(s), tests and pipeline, and one ready reply per thread (1–2 plain sentences each: what changed and the commit, no agent names).
