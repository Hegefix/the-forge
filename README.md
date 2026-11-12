# The Forge

A Claude Code plugin for running parallel Claude Code sessions: one lead session (the coordinator) hands tasks to worker sessions, each in its own git worktree, tmux session and Terminal window.

Version 0.9.0. Besides the coordinator and worker skills, it has skills for merge trains, integration builds, QA hand-offs, QA runs on simulators, review rounds, browser work and meeting prep. It also has launch and close scripts, permission profiles (research, code, device, browser, watcher) and optional helpers, among them a token meter with a gated launch script for a weekly token budget and a board watch. Two helpers need a model: the comms watcher and the scribe. Each of them runs one short headless `claude -p` pass on a schedule, not a long session.

## What's new

- **0.9.0:** `qa-run` skill for testers on a Mac (iOS simulators and Android emulators, a PASS / FAIL / BLOCKED table with evidence, a per-project config).
- **0.8.0:** the token meter reads the plan's real usage (with a `statusLine` script), pauses and resumes with the laptop lid, and fixes reading age and reset; guidance for load checks.
- **0.7.0:** a board watch helper that audits tickets against MRs.

## Install

```sh
claude plugin marketplace add Hegefix/the-forge
claude plugin install the-forge@hegefix
```

To update an earlier install: `claude plugin marketplace update hegefix`, then `claude plugin update the-forge@hegefix`.

What's in the kit, what it needs and how to start: [plugins/the-forge/README.md](plugins/the-forge/README.md).
