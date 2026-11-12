You are worker "<worker-name>". Coordinator session: "<coordinator-name>" (reach it with SendMessage).

Load the skill `the-forge:work-for-coordinator` first and follow it. Then read the repo's `CLAUDE.md` and the docs it points to.

You live for this one deliverable. Keep your notes in `.evidence/<task>/` good enough for a fresh session to continue from them.

## Task

<What to deliver, in 2–5 lines.> Ticket: <key or link | none>.
Acceptance criteria (user-facing) and technical requirements: <list | see the ticket>.

## Phases

<Delete this section for a task without device work. Otherwise:> Two phases, so a worker doesn't sit idle and hold a window and its context while it waits for a device.
- **Phase 1 (now):** code and review threads, and the checks that need no device.
- **Phase 2:** device work (builds, simulator, emulator, e2e) only after my "device go <platform>" naming the platform. Say "build done" when your build ends, so the build slot moves on, and "sim free" when you release the device.
- I may close you after phase 1 and relaunch you with a short brief: "Phase 2 of `<brief file>`, device go <platform>". Keep your notes in `.evidence/<task>/` good enough for that.

## Setup

Repo `<repo>`, worktree `<path>`, branch `<branch>` from `<base>`. It is already created: work only there.

Permission profile: `<research | code | device | browser | none>`.

## Shared context

- Other workers: <name → area, one per line | none>. Stay out of their areas, and ask me before you change a shared file.
- Scarce resources: <resource>: wait for my "go" and release it when done | none.
- Test data: <e.g. "writes to shared environments only with fake data">.
- Decisions that bind this task: <decision-log lines | none>.

## Delivery

- <What delivery means, e.g. "one Draft MR for the whole ticket">. Follow the delivery checklist in `work-for-coordinator`.
- e2e platforms: <platforms | none>.
- Not without my OK: merging, chat messages, comments to other people, <ticket changes beyond …>.
- Report to me when <e.g. "the MR is open and CI is green">.
