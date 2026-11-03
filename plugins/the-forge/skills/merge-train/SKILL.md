---
name: merge-train
description: >-
  Use when several approved MRs or PRs have to land in the default branch in a set
  order, when an approved MR conflicts with the default branch after another one
  merged, when MRs are stacked on each other, when a test fails only once two MRs
  meet, or when an MR shows "needs rebase" under a semi-linear merge rule.
---

# Merge train

Approved MRs land one at a time. Each merge moves the default branch, so the next branch is brought up to date, checked, and merged only on green. One worker updates the branches; only the coordinator merges.

## Roles

| Who | Does | Never |
|---|---|---|
| Coordinator | sets the order, checks each "ready" line, merges, says "next" | edits a branch itself |
| Worker (`code` profile, or `device` for the e2e at the end) | updates one branch, runs the checks, pushes, reports "ready" | merges, rebases a pushed branch, force-pushes, starts the next branch before "next" |

## Order

- **Replay solved conflicts.** If an integration branch combined these MRs before (skill `integration-build`), use its merge order: its `conflicts.md` then says how each conflict was solved.
- **App-wide changes first** (ids, CI, lint rules), then the base of a stack before its children, then features.
- **The human may merge out of order.** Re-plan from the new default branch; don't undo anything.

## The loop, per MR

1. Worker: `git fetch origin && git merge origin/<default>` in that MR's worktree. A merge commit: rebasing an approved branch rewrites what the reviewers approved and needs a force push.
2. Solve conflicts from the reference: `git show <integration-sha>:<path>` and `conflicts.md`.
3. Run the repo's checks (lint, types, format, unit tests). Fix what the merge breaks. Never weaken a test or a budget.
4. Push (a normal push) and wait for the pipeline.
5. Report one line: `!<n> ready: <merge sha>, conflicts <files | none>, tests <count>, pipeline <id> green`. Wait for "next".
6. Coordinator: approval still there, pipeline green, MR head equal to the reported SHA. Merge with a head guard: `glab mr merge <n> --sha <sha>`, `gh pr merge <n> --match-head-commit <sha>`. Log it, then say "next".

After the last MR: smoke plus one flow per merged ticket, from the default branch's head.

## Special cases

| Case | Do |
|---|---|
| Stack: parent approved, child still in review | Merge the parent, then retarget the child to the default branch; the child gets a default-branch merge first. |
| Stack: the human wants one MR to review | Collapse it: merge the child into the parent's branch. Then the parent carries both. That merge is not on the default branch: check `target_branch` before you report "merged". |
| A test passes on each MR alone and fails once both are in | Record "whichever of !A / !B lands second updates `<test>`". The second MR's worker fixes it in its default-branch merge. |
| "Needs rebase" under a semi-linear merge rule | Merge the target branch into the MR branch and push normally. The target is then an ancestor, which is all the check wants. |
| Head pipeline stuck on an old external status | Start a fresh pipeline for the MR. Never write a status by hand. |
| Diff became empty (`git cherry origin/<default> <branch>` shows only `-`) | Nothing to merge. Tell the MR's owner; don't touch their branch. |

## After each merge

- Keep a train worktree until its MR has merged; the janitor (or you) removes it after.
- Move the ticket as the workspace says, for example to the QA status (skill `qa-handoff`).
- Close the train worker when the train is done (`close-worker.sh`).

`references/train-brief.md` is a brief for the train worker.

## Red flags

| Thought | Do instead |
|---|---|
| "A rebase gives a cleaner history" | Merge commit. A rebase needs a force push and drops the approval's base. |
| "CI is green, I'll merge it myself" (worker) | Report "ready: <sha>". Only the coordinator merges. |
| "I'll update all four branches now and report once" | One at a time. Each merge moves the default branch. |
| "Fix the cross-MR test in the first MR" | It passes there. The MR that lands second fixes it. |
| "The pipeline is still running, but it will pass" | Wait for green. |
