# Integration build templates

Both files live in `.evidence/<name>/`. Fill them in as you go, not at the end.

## conflicts.md

```markdown
# <name>: merge conflicts (<branch>, local only)

Base: origin/<default> <sha>. Merged in this order with `git merge --no-ff origin/<branch>`.
Redo these when the MRs merge into <default> one by one. "HEAD" = this branch with the MRs above
merged; "theirs" = the branch being merged.

## !<n> <branch> (<count> files | no conflicts)

<One line: what theirs changes that collides.> Rule used: <e.g. "HEAD's structure, theirs' features added into it">.

1. `<path>`
   - HEAD (!<m>): <what it had>.
   - Theirs: <what it had>.
   - Result: <what the file has now, and why>.

## Fixes the combination needed

- <commit sha> <what>: <why>. Merge note: whichever of !<a> / !<b> lands second <does what>.

## Lockfile and generated files

<How they were regenerated, e.g. "took HEAD's lockfile, then the package manager re-resolved">.
```

## README.md

```markdown
# <Demo | QA> build <name> (<date>)

- Branch `<branch>` in `<worktree>`, from origin/<default> <sha>. Local only: never pushed, no MR.
- Build: <variant>, app id <id>, build <number>, commit <sha>. Artifact <path>, <size>, sha256 <hash>.
- Conflicts and how they were solved: conflicts.md.

## Merged MRs, in this order

| # | MR | Ticket | What | Walkthrough |
|---|----|--------|------|-------------|

Skipped: <MR and why | none>.

## What it took on top of the merges

- <commit: what and why>

## Checks

- Lint, types, unit tests: <result; any failure from the combination and its merge note>.
- Devices: <flow → PASS/FAIL per platform>.

## Demo script

Safety, all through the demo: never delete the account, never change its email or password, never
accept a legal document or finish a test for real on a shared account.

1. **<Feature>** (<ticket>, <platform>). <What to tap, what you see.> *<What it writes, if anything.>*

## Data the demo needs

- <feature>: <flag, account right, data the account must have, …>
```
