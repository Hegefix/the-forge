---
name: review-round
description: >-
  Use when the human is set as a reviewer on someone else's MR or PR, when an MR the
  human already reviewed gets new commits, a rebase or a squash, or when a verdict
  and a ready-to-post review comment are needed on another person's change.
---

# Review round (someone else's MR)

A research worker reviews the MR and returns a verdict with a comment the human can post. Nothing is posted, approved or resolved before the human's OK for that MR.

## Start it

- **As soon as the human is added as a reviewer,** without being asked. Again when new commits land after their review.
- **A worker with the `research` profile,** with a worktree on the MR's source branch: `bash ${CLAUDE_PLUGIN_ROOT}/skills/coordinate-workers/scripts/launch-worker.sh … --base origin/<source-branch> --branch review/<n> --profile research`. Never a background subagent: it would run with the coordinator's permissions, approve and comment included, limited only by its prompt.
- The brief: `${CLAUDE_SKILL_DIR}/references/review-brief.md`.

## What the worker does

1. **Reads** the description, the full diff, every discussion (author, date, resolved or not), the commits and the pipeline, through `gh`/`glab` read commands.
2. **Checks the human's earlier comments:** each one fixed (by which commit), answered, or still open.
3. **Reviews:** correctness, edge cases, tests that would fail without the change, compatibility, release risk, and any claim in the description that the diff doesn't make true.
4. **Reports** in at most 20 lines: the verdict (approve / approve with nits / request changes), findings by severity with `file:line`, and a ready comment in the human's voice (2–5 plain sentences), or "no comment needed".

## The coordinator

- Sends the human one line: the verdict and the ready comment.
- Posts it, approves or resolves the human's own threads only after their OK for that MR. Merging someone else's MR stays theirs.
- Closes the worker, and removes the review worktree and branch: they have no MR, so the janitor leaves them.

## Rebase, squash or new commits after a review

Before a new round, compare what changed:

```bash
git range-diff <old-base>..<old-head> <new-base>..<new-head>   # commit by commit
git diff <old-head> <new-head> -- . ':!<lockfile>'              # the code itself
git cherry origin/<default> <branch>                            # "-" = already on the default branch
```

- **Same diff as the one reviewed,** apart from changes already on the default branch (a dependency bump that landed separately): no new round. The approval stands; log why.
- **New code:** a round on the new commits only, plus the earlier threads.

## Red flags

| Thought | Do instead |
|---|---|
| "A quick subagent can review this" | A `research` worker. A subagent has your permissions. |
| "The verdict is approve, I'll approve" | One line to the human, then their OK. |
| "They rebased, so it's a full new review" | Compare first. Same diff, same approval. |
| "I'll leave the review worktree, the janitor cleans up" | No MR, so no janitor. Remove it. |
