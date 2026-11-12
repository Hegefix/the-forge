---
name: qa-run
disable-model-invocation: true
description: >-
  Use when a tester asks to test tickets or a build of a mobile app on iOS
  simulators and Android emulators, to run the regression flows, or to collect
  evidence and draft the tracker comment for a ticket.
---

# QA run

For a tester who works from a Mac with Claude Code. Input: ticket keys and a build, or "regression on build X". Output per ticket: a PASS / FAIL / BLOCKED table with evidence files and a draft comment. The developers' side of the hand-off (build, "How to test", build note) is the skill `qa-handoff`.

## Rules

- **Nothing leaves the Mac without the tester's "post".** Post or attach per ticket, only after that ticket's draft was shown and approved. Never change a ticket status, never write to chat.
- **Never type, print or log a password.** Sign in with the project's sign-in command only. If there is none, ask the tester to sign in by hand on the device.
- **Test accounts only**, and no personal data on a screen you capture. Respect the account limits in the ticket's "How to test" (never delete the shared account, change its email, accept a legal document).
- **Don't fix, don't guess.** Report what the screen shows. A step you could not do is BLOCKED with the reason, not FAIL.
- **Devices:** at most one iOS simulator and one Android emulator booted. Shut both down at the end, and on any stop.

## 1. Start

1. Run `bash ${CLAUDE_SKILL_DIR}/scripts/preflight.sh`. It reads the config, checks the tools and lists booted devices. A missing tool: point to `${CLAUDE_SKILL_DIR}/references/setup-mac.md` and stop.
2. No config: copy `${CLAUDE_SKILL_DIR}/templates/qa-run.json` to `.claude/qa-run.json` in the project and fill it with the tester (fields: `${CLAUDE_SKILL_DIR}/references/config.md`).
3. Read each ticket with the Atlassian MCP tools: summary, acceptance criteria, and the newest "How to test" comment. No Atlassian tools loaded: tell the tester to connect them (setup-mac.md, "Claude Code connectors") and stop.
4. Compare the build with the tickets: the build number or commit in the build note must contain the ticket's change. If unsure, ask before testing a wrong build.

## 2. Pick devices

From the ticket, not from habit:

| Ticket says | Boot |
|---|---|
| Phone UI, general | One iOS phone, one Android phone (the config's defaults) |
| Tablet or layout on large screens | iPad simulator + Android tablet emulator |
| WebView, old device, a crash on one maker's phone | The Android API levels in the config (one at a time), plus the default iOS phone if it also affects iOS |
| iOS only or Android only | That platform only |

Boot with `xcrun simctl boot <name-or-udid>` and `emulator -avd <name> -no-snapshot-save -no-boot-anim &`, wait for `adb shell getprop sys.boot_completed` to print `1`. Several API levels run one after the other, so shut an emulator down before the next boots.

## 3. Install and sign in

- `bash ${CLAUDE_SKILL_DIR}/scripts/install-build.sh <ios|android> <device> <build file>` installs it. **An iOS simulator needs a simulator `.app` (or a zip of one).** A TestFlight or App Store `.ipa` can't run on a simulator: tell the tester to ask the developers for a simulator build of the same commit, and mark the iOS steps BLOCKED until then. Android takes an `.apk`; an `.aab` must be turned into an APK first (setup-mac.md).
- Run the config's `sign_in_command` for the device. Check with a screenshot that the home screen shows, with no personal data.

## 4. Walk the steps

For each acceptance criterion and each "How to test" step:

1. A flow in the config's `flows.dir` covers it: run it with `QA_LOGS=<evidence_dir>/<TICKET>/logs bash ${CLAUDE_SKILL_DIR}/scripts/run-flows.sh <device> <flows-dir> <flow>`, so the logs stay out of the app's working tree. A pass counts only for what the flow asserts, so say which flow and what it checks.
2. No flow covers it: write a temporary Maestro flow in the evidence folder (`tmp-*.yaml`, `takeScreenshot` after each step) or drive the device with `xcrun simctl` / `adb`. Delete temporary flows when done, and offer the good ones to the developers as new flows.
3. Take a screenshot after the result, named `<TICKET>-<criterion>-<device>.png`. Record a short video (`xcrun simctl io <udid> recordVideo`, `adb shell screenrecord`) only when motion matters: animation, scrolling, a video player, a loading state.
4. Write one result per criterion and device with what you saw, in the screen's own words. A FAIL gets the exact step, expected and seen. Check once more on a fresh launch before calling it FAIL.
5. Compare against the ticket's text and design where the ticket attaches one. Visual differences go into the table as "Note", not FAIL, unless the criterion names them.

Web tickets (a web page, an admin site): use a browser-testing skill if one is installed (for example `user-test`), otherwise Claude in Chrome, with the same evidence rules. A human signs in; the skill never types a password in a browser either.

## 5. Evidence and report

Save to `<evidence_dir>/<TICKET>/`: screenshots, videos, `report.md`. Format and the draft comment: `${CLAUDE_SKILL_DIR}/references/report.md`. Show the tester the table and the draft, then wait.

On "post <TICKET>": add the comment through the tracker MCP, and attach files if the connector can. If it can't, tell the tester which folder to drag into the ticket. The status stays as it is; the tester or developer moves it.

## Regression mode

Input: "regression on build X" (flows from the config's `flows.regression`, or the names the tester gives).

1. Install the build on one iOS and one Android device, sign in.
2. Run `run-flows.sh` per platform. It prints one line per flow and keeps full logs on disk.
3. Read a log only for a failed flow. Rerun each failure once; a pass on rerun is a "flake", listed as such with both results.
4. Report one line per flow per platform: `PASS`, `FAIL (step)`, `FLAKE`. Then the same table and draft comment shape as above, with the build as the subject instead of a ticket.

## Finish

Shut down the simulator and emulator, delete temporary flows and builds you extracted, and say where the evidence is. List anything BLOCKED with what unblocks it.

## Red flags

| Thought | Do instead |
|---|---|
| "The flow passed, so the criterion passes" | Check that the flow asserts that criterion. Else test it by hand. |
| "TestFlight build, I'll try the simulator" | It can't run. BLOCKED, ask for a simulator build. |
| "Looks fine, I'll move the ticket" | Never. Draft, wait for "post", leave the status. |
| "Two tablets and three API levels at once" | One simulator and one emulator at a time. |
| "Let me type the password once" | Use the sign-in command, or the tester signs in. |
