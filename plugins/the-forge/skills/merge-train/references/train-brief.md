You are worker "<worker-name>" (`code` profile; `device` if it runs the e2e at the end, devices only after my "go devices"). Coordinator: "<coordinator-name>" (SendMessage). Load the skills `the-forge:work-for-coordinator` and `the-forge:merge-train` and follow them.

Goal: land these approved MRs in `<default>` today, in this order. The coordinator merges. You bring each branch up to date, one at a time, and wait for "next" between them, because each merge moves `<default>`.

1. !<n> `<branch>` (`<worktree path>`)
2. !<n> `<branch>` (`<worktree path>`)
<…>

Your own worktree is a scratch branch. Work in the worktrees above with `git -C` or absolute paths, and `git pull` each one first.

Per MR:
a. `git fetch origin && git merge origin/<default>`: a merge commit. No rebase, no force push.
b. Solve conflicts. Reference: every combination is solved on the local branch `<integration branch>` (commit `<sha>`; `git show <sha>:<path>`) and in `<conflicts.md path>`. Known cross-MR fixes: <"whichever of !A / !B lands second updates <test>" | none>.
c. Checks: <lint, types, format, unit tests>. Fix what the merge breaks. Never weaken a test or a budget.
d. Push (normal), wait for the pipeline, then send me one line: `!<n> ready: <merge sha>, conflicts <files | none>, tests <count>, pipeline <id> green`. Wait for "next".

After the last one: <wait for "go devices", then run smoke plus one flow per merged ticket on <platform> from `<default>`'s head, and report | nothing>.

Don't touch titles, labels, reviewers or descriptions. Don't merge, approve, comment, or message anyone but me. Don't open env or credential files.
