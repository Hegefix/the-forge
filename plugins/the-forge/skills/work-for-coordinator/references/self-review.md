# Self-review with lens subagents

Reviewer subagents read your diff, one lens each, before the human's check. They catch what a single pass by the author misses, so the human and the reviewers spend their time on what's left.

It runs once per MR: before the first ready line, or before the first final report when the MR gets no human check. A later review-fix or merge-train worker on the same MR skips it.

## Which lenses

| Risk | Lenses |
|---|---|
| 0–1 | none: skip it, and write "Self-review: skipped (Risk <n>)" |
| 2–3 | adversarial |
| 4–5 | adversarial, verification gap |

Every lens is a subagent turn that re-reads your diff, so the count follows the risk: at Risk 2–3 the adversarial lens tries bad inputs and odd states, and at Risk 4–5 the verification-gap lens adds the check that each new branch has a test that fails without it. Add the edge-case or ticket-fit lens on top only when the coordinator or the brief asks for it.

Use the Risk score your MR description will carry. If a finding shows the score is too low, raise it and add the lenses the new score calls for to the same pass, before the fix round. A raise that only shows in the re-check goes to the coordinator instead.

## When

Once the code is complete, committed, and the repo's fast checks (lint, types, unit tests) pass. Run it before the full e2e run and before the walkthrough: the fixes then ride along with that run, and the walkthrough gets the result line.

## Running the lenses

1. `git fetch origin`. The base is the MR's target branch: for a stacked MR, the branch under it, not the default branch.
2. Commit your task's files. Then note `git rev-parse HEAD`, `git status --short`, and the `git stash list` entries that name your branch. Never stash: the stash stack is shared with every other worktree.
3. Start one subagent per lens, all in one message so they run in parallel, with the default subagent type and the smaller model (`model: "sonnet"` in each Agent call, or the workspace's choice): a lens reads and reports, it doesn't need the strongest model. Each prompt is the shared prompt below with one lens paragraph.
4. Wait until every lens has returned before you edit anything. Then compare HEAD, the status and your branch's stash entries with step 2; entries for other branches belong to other sessions. If anything changed, a subagent wrote: put it back, check the finding behind it yourself, and tell the coordinator if it pushed. Restore a stash entry with `git stash apply <sha>`; never pop or drop one.

### Shared prompt

    You review a change, read only. Decide by reading the code and the tests. Don't edit, create, delete, stash or check out files; don't run tests, builds or device commands; don't commit, push, post or comment. `git show origin/<base>:<file>` shows the old code.
    Diff: `git diff origin/<base>...HEAD` in <worktree path>. Read the changed files around each hunk as needed.
    Task: <2–5 lines>. Acceptance criteria: <list | none>.
    Lens: <lens paragraph>
    Report every finding, one per line, and nothing else:
    <high|medium|low> | <file:line> | <what goes wrong: the input or state, and the wrong result> | <suggested fix>
    high: a wrong result, crash, data loss or security hole in a realistic case. medium: wrong in an uncommon case, or a new branch with no test. low: rare, or clarity only.
    If you find nothing, answer "no findings".

### Lens paragraphs

- **Adversarial:** Try to break the change. Bad and unexpected inputs; state left behind by an earlier call or by a failure halfway through; errors that are swallowed or reported wrong; retries; two calls at once; events in an unexpected order (async work, network, app lifecycle). Name the concrete case that fails.
- **Edge cases:** Empty, null, one, many and maximum values; long text and unusual characters; time zones, locales, number and date formats, right-to-left text; each platform and OS version the code runs on; offline and slow network; first run, and an upgrade from an older version with old data.
- **Verification gap:** For each acceptance criterion and each new branch or condition in the diff, find the test that would fail if that code were removed or inverted. Report each one that has no such test, and name the test that would catch it. A test that only renders, or mocks the code under test, doesn't count.
- **Ticket fit:** Compare the diff with the task and its acceptance criteria. Report criteria that are missing or only partly met, behaviour the task didn't ask for, and changes outside its scope.

## Triage

Count a finding that several lenses report once.

| Finding | What you do |
|---|---|
| Real and in scope | Fix it, with a test that fails without the fix where the repo has tests. |
| Wrong, already covered, or intended | Reject it with a one-line reason: the test at `file:line`, the decision, the acceptance criterion. |
| Real, but work outside the task | Defer it: a line in `deferred.md`. Don't do it in this MR. Tell the coordinator about a deferred `high` now. |
| Your own change that is outside the task | Take it out of this MR: that is the fix. |
| Needs a decision you can't make (scope, a contract, product behaviour) | Ask the coordinator. |

Severity doesn't choose the row: a real `low` in scope is a cheap fix, and a `high` about work outside the task is still deferred.

## Limits

- **One fix round:** fix everything you accepted, run the fast checks, commit.
- **One re-check:** run again only the lenses that had a fixed finding, with the shared prompt and the same checks, on the fix round's diff (`git diff <HEAD noted in step 2>..HEAD`). Its prompt lists the fixes, and the rejected and deferred findings with their reasons, marked "don't report again"; it asks only whether each fix holds and whether it broke anything in the changed hunks. Don't start another round from it: a `high` goes to the coordinator, and holds the ready line until it's decided; the rest go into the walkthrough as open points.

## Record

One line in the walkthrough, in the MR description's Details block, and in your report to the coordinator. Leave out the parts that are zero:

    Self-review (<lenses>): <n> findings, <f> fixed, <r> rejected (<reason>; <reason>), <d> deferred, <q> to the coordinator, <o> open. Re-check: fixes hold | <what broke>.
