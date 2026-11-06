---
name: review-loop
description: >-
  Use when reviewers left threads on our own MRs or PRs, when an approval is missing
  or was reset by new commits, when deciding who answers a review comment, or when
  the goal is to get a set of MRs approved by a deadline such as "today".
---

# Review loop (our own MRs)

Every reviewer thread gets triaged, fixed by a worker, answered with the commit, and then the approval is asked for again. The coordinator posts the replies; workers fix code; the human decides disagreements.

## Triage each open thread

Read the full discussion through the API, not the notification. Then:

| Kind | Example | Who acts |
|---|---|---|
| Mechanical | a typo, a named missing test, a rule the repo requires, dead code | a worker fixes; the coordinator replies with the commit |
| Judgment we agree with, one obvious fix | a real bug the reviewer found | a worker fixes, with a test that fails without the fix; the coordinator replies |
| Judgment with several fixes, or we disagree | an alternative design, scope, architecture, "won't do" | the human decides (a D item, with the reply text in the batch) |
| Valid but out of scope | "also clean up X elsewhere" | reply "follow-up"; a line in the task's `deferred.md` (by the fix worker, or by you when none runs); the ticket draft goes to the human with the feature's retrospective, or sooner if urgent |

Unsure which kind: treat it as judgment.

## Fix

- One fresh worker per MR (or one for a few small MRs, one after the other), started from the evidence folder. The brief lists each thread: id, `file:line`, the reviewer's words, what we do (`${CLAUDE_SKILL_DIR}/references/fix-brief.md`).
- The worker fixes, adds the test, runs the checks, pushes normally, and reports the commit plus one ready reply per thread: 1–2 plain sentences saying what changed, with the commit.
- It doesn't touch the title, labels, reviewers or the human's check line.
- Stop after 5 fix rounds on one MR and report. Never weaken a test.

## Reply and resolve

- **Reply** on each thread: what changed, and the commit. A reply that only says what changed is factual; a disagreement is a D item.
- **Resolve only threads we answered, on our own MRs.** A thread the reviewer marked blocking stays for the reviewer to resolve, unless the team's habit is otherwise. Threads on someone else's MR are not ours to resolve without the human's OK.
- **Ask for the approval again** in one message: per reviewer, which MRs now have every comment fixed and answered. If the project resets approvals on new commits, every pushed fix needs that ask.

## Deadline: "approved today"

- Split the MRs between reviewers so nobody gets all of them, and give the next one to whoever has the fewest.
- Fix and reply as threads come in. Don't hold the fixes for the end.
- Keep one line per MR: approvals needed and given, open threads, pipeline.
- Send review requests and re-asks as one message with a line per MR: a chat send may cost the human an approval click.

Without a deadline, pace yourself: reviewers who get too many MRs at once review worse. Release Drafts in small batches, on the human's go.

## Red flags

| Thought | Do instead |
|---|---|
| "The reviewer is wrong, I'll explain why" | D item, with the draft reply. |
| "Fixed, so I'll resolve their blocking thread" | Reply, and leave it for the reviewer. |
| "I'll resolve the answered threads on their MR too" | Not our MR: the human's OK first. |
| "I'll batch the fixes and reply at the end of the day" | Fix and reply per thread, as they come. |
| "All the MRs to the fastest reviewer" | Split them; the next one goes to whoever has the fewest. |
