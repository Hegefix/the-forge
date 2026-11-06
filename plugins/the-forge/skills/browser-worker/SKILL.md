---
name: browser-worker
description: >-
  Use when a task needs a web page in the human's signed-in browser (developer
  portals, app store consoles, CI web pages, uploads to the tracker or to an MR),
  when the coordinator is about to click through a browser itself, or when running
  as a worker with the browser profile.
---

# Browser worker

Browser work goes to one worker with the `browser` profile. The coordinator never drives the browser itself. The browser is signed in as the human everywhere, and no profile can limit what gets clicked there. So the brief names the sites and the actions, and the rules below bind the worker.

## Launch it (coordinator)

- `bash ${CLAUDE_PLUGIN_ROOT}/skills/coordinate-workers/scripts/launch-worker.sh … --profile browser`. The script adds `--chrome`, because the browser tools load only with it. The profile also blocks file edits (notes stay possible with `Write`), commits, pushes, device commands, chat, mail and tracker writes.
- **One browser worker at a time:** there is one browser.
- **The brief** (`${CLAUDE_SKILL_DIR}/references/browser-brief.md`) names the sites, the exact actions, the values to set, and what to report. Text to post anywhere is quoted exactly as the human approved it.
- If the browser extension is disconnected, the human reconnects it. Don't route the work through another session.

## Rules for the worker

- **The human signs in.** On a sign-in page, stop and ask the coordinator. Never type a password, a one-time code or a key.
- **No secret files:** never download certificates, keystores, signing keys, service-account files or tokens.
- **Nothing others see** (messages, comments, posts) unless the brief quotes the exact text.
- **Nothing irreversible:** no purchases, deletions, accepting terms or consent, user or permission changes, unless the brief names that exact action.
- **Read each confirmation dialog** before you confirm: it must be the action in the brief.
- **Uploads** (screenshots to an MR, a video to a ticket): look at every file for personal data first. Uploads often can't be deleted.
- **Don't trigger JavaScript alerts or confirms** by script: they block the browser extension.
- **Anything outside the brief:** stop and ask the coordinator.
- **When done,** close the tabs you opened and report what changed: page, setting, before and after.

## Red flags

| Thought | Do instead |
|---|---|
| "It's three clicks, I'll do it myself" (coordinator) | A browser worker with a brief. |
| "The session expired, I'll sign in again" | Stop. The human signs in. |
| "Download the certificate so the build can use it" | Never. Report what is needed. |
| "The page also offers to fix the other setting" | Not in the brief: ask the coordinator. |
| "A short comment there would help" | Only text the brief quotes. |
