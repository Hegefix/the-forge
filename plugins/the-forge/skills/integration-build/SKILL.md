---
name: integration-build
description: >-
  Use when a demo, a hand test or a QA build needs several open MRs or PRs together
  before they merge, when someone asks for "everything in one branch" or "one build
  with all of it", or when the conflicts between open MRs should be solved once,
  ahead of their merges.
---

# Integration build

All open MRs merged into one local branch and built once. The branch is a throwaway: never pushed, no MR. Each MR still goes through review and merges on its own. Its conflict log is the recipe the merge train replays later (skill `merge-train`).

One worker does it, with the `device` profile when the build runs on devices. The coordinator sets the order and gives the device "go".

## Steps

1. **Branch:** `git worktree add -b <demo|qa>/<name>-<date> <workspace>/.worktrees/<repo>/<name> origin/<default>`. Local only.
2. **Order:** app-wide changes first (ids, CI, lint rules), then the base of each stack, its children, then features. Skip a merge that takes more than ~15 minutes, and list it.
3. **Merge** each with `git merge --no-ff origin/<branch>`. Log every conflict in `conflicts.md` (`references/templates.md`): per MR and file, what HEAD had, what theirs had, the result, and the rule you used.
4. **Fix what only the combination breaks:** a lint rule from one MR firing on another's code, a test that meets another MR's change, an id one MR renamed. One commit each, listed in `conflicts.md` with its merge note: "whichever of !A / !B lands second fixes `<test>`".
5. **Demo-only changes** (a debug switch, a row ungated for the build) are separate commits with a `demo:` or `qa:` prefix, never in an MR. Whether a QA build keeps them (ungated) or reverts them is the human's call. The build note names what is experimental.
6. **Check** the combined tree: lint, types, unit tests.
7. **Build** the variant the use needs: a development build for a demo, the QA variant for QA (never a debug or development one). Note the build number, the commit, and the artifact's size and sha256.
8. **On devices,** after the coordinator's "go": sign in with the workspace's sign-in helper (one try), then smoke plus one flow per feature, on each platform. Skip flows that write to a shared account: delete, accept, finish, change email or password.
9. **README.md** next to `conflicts.md`: the merged MRs (order, MR, ticket, what, walkthrough), what it took on top, the checks, the devices, a demo script with its safety rules, and the data the demo needs (`references/templates.md`).
10. **Clean up:** delete native build output. Keep the branch and the evidence folder until every MR has merged, because the merge train replays them.

## QA from an integration branch

QA builds normally come from the default branch. Testing open MRs before they merge is the human's call. The build note lists the MR heads it contains, and later review fixes it doesn't.

## Red flags

| Thought | Do instead |
|---|---|
| "I'll push the demo branch so the human can pull it" | Never push it. Give the worktree path. |
| "I'll fix this conflict in the MR branch right away" | Log it. MR branches change in the merge train. |
| "The demo switch can quietly stay in the QA build" | The human decides, and the build note says so. |
| "The flow needs a finished test, I'll finish it on the shared account" | Skip it, and say what was skipped. |
