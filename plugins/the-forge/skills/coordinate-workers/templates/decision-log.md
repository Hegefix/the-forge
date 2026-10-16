# Decision log

Format: `- <date> [<class>] <decision> — <why> (decided by: <worker|coordinator|<human's name>>)`

Classes: `B` a worker's debatable call, `C` a cross-agent call by the coordinator, `D` answered by the human, `rule` a new standing rule the human approved, `standing rule` an action taken under a standing rule, `A` or `fyi` a result worth knowing later. Group entries under a `## <yyyy-mm-dd>` heading per day, newest at the bottom.

Be specific: results, root causes, commit SHAs, MR ids, `file:line`. The next coordinator takes over from this log; if a scribe runs, it builds the team's notes from it; the comms watcher reads its tail to skip what's already handled. What isn't here is lost when the coordinator's context ends.

Examples of the shape (delete them):

- 2026-01-15 [B] Pin the linter to the exact current version instead of migrating to its renamed rules — keeps coverage identical; the migration is its own task (decided by: worker)
- 2026-01-15 [C] Merge order !12 → !14 → !13; each later branch merges the default branch and regenerates the lockfile (decided by: coordinator)
- 2026-01-15 [D] D-4: keep the old API field until the mobile release ships, then remove it in a follow-up ticket (decided by: <human's name>)
- 2026-01-15 [rule] One MR per feature; sub-tasks only when the work is split between parallel workers (decided by: <human's name>)
- 2026-01-15 [standing rule] !12 taken out of Draft after the human's hand test and code read; "Hand-tested and code reviewed" line and `ai:generated` label added, reviewers set (decided by: coordinator)
- 2026-01-15 [A] !13 review fixes pushed (a1b2c3d keyboard inset, e4f5a6b label id), CI green, merged (9f8e7d6); worker closed, transcript 41 MB (decided by: coordinator)

## <yyyy-mm-dd>

