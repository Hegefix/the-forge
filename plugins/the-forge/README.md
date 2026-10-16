# The Forge

A workflow for running parallel Claude Code sessions. One lead session (the coordinator) hands tasks to parallel worker sessions, each in its own git worktree, tmux session and Terminal window. The coordinator decides what it can, batches the rest for one human, and keeps the decision log and the handover note. Optional helpers read the feeds, watch the MRs, clean up, watch the laptop's load and, if you keep a knowledge base, write the notes. The human answers decisions by id, tries every change by hand and reads its code before it goes to review.

## What's in the kit

| Part | What it is |
|---|---|
| [`coordinate-workers`](skills/coordinate-workers/SKILL.md) | Skill for the coordinator: workspace setup, launching workers, helpers, agent lifetime, delivery from Draft to merge, the tracker, decision classes, escalation batches, decision log, standing rules. |
| [`work-for-coordinator`](skills/work-for-coordinator/SKILL.md) | Skill for a worker: who decides what, how to ask, permission blocks, scarce resources, e2e scope, the delivery checklist (one MR per feature, Risk score, a short MR description, walkthrough, review triage, ticket sign-off). |
| [`launch-worker.sh`](skills/coordinate-workers/scripts/launch-worker.sh) | Creates the worktree and branch, starts the worker in tmux with its brief and permission profile, and opens a Terminal window. |
| [`workspace-claude-md.md`](skills/coordinate-workers/templates/workspace-claude-md.md) | The workspace `CLAUDE.md`: settings, helpers, comms watcher sources, standing rules to keep or delete. |
| [`handover.md`](skills/coordinate-workers/templates/handover.md), [`decision-log.md`](skills/coordinate-workers/templates/decision-log.md), [`worker-brief.md`](skills/coordinate-workers/templates/worker-brief.md) | The coordination files and the brief every worker starts from. |
| [`permission-profiles/`](skills/coordinate-workers/templates/permission-profiles/README.md) | Deny-rule settings files: `research`, `code`, `device` for workers, `watcher` for helpers. |
| [`tools/`](skills/coordinate-workers/templates/tools/README.md) | Helpers, each optional and independent: comms watcher, MR watch, janitor, load check, e2e runner, tracker helper (Markdown to ADF checkboxes), and the scribe for teams that keep an LLM wiki or knowledge base. |
| [`examples/module-boundaries/`](skills/coordinate-workers/templates/examples/module-boundaries/README.md) | Optional example: lint rules that keep modules from importing each other's internals, and pages from importing pages. |

## Needs

Install with `claude plugin marketplace add Hegefix/the-forge`, then `claude plugin install the-forge@hegefix`. macOS with Terminal, `tmux`, `git`, `jq` and Claude Code. The janitor and MR watch need `python3` and `glab` (GitLab); the e2e runner needs Maestro; the scribe needs a knowledge base it can write to. Workers use `ListAgents` and `SendMessage` to talk to the coordinator.

## How to start

1. Make a workspace folder that holds your repos (or links to them). It is not a repo itself.
2. Start Claude Code there with a fixed session name, for example `claude --name coordinator`, and ask it to set up the workspace with the `coordinate-workers` skill. On the first run it:
   - writes the workspace `CLAUDE.md` from the template and asks you only for the settings without a default;
   - creates `coordination/handover.md` and `coordination/decision-log.md`;
   - copies the permission profiles to `coordination/permission-profiles/` and fills in your MCP server names with you;
   - copies the helpers you want to `coordination/tools/`, and tries the janitor in dry-run mode. The scribe is optional: take it only if you keep an LLM wiki or knowledge base (an MCP server such as an Obsidian vault). Without it, the coordinator keeps the decision log and refreshes the handover note itself.
3. Give it a task. It writes a brief, picks the profile from the task type, and launches a worker in its own worktree and Terminal window.
4. Answer its decision batches by id ("D-3 ok, D-4 alt"). Approve a recurring answer as a standing rule when it proposes one.
5. When your context gets large, start a fresh coordinator with the same session name. It takes over from the handover note.

## Workspace layout

```
<workspace>/
  CLAUDE.md                      settings, helpers, standing rules
  coordination/
    handover.md                  takeover steps, state, live workers, gotchas
    decision-log.md              every B, C and D decision, results, root causes
    permission-profiles/         research.json, code.json, device.json, watcher.json
    tools/                       the helpers you picked: comms-watch/, mr-watch/, janitor/, load-check/,
                                 e2e/, tracker/, scribe/ (optional)
  .worktrees/<repo>/<task>/      one per worker
  .evidence/<task>/              MR description drafts, walkthroughs, screenshots, test results
  <repo>/ …
```
