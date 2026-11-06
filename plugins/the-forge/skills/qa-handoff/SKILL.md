---
name: qa-handoff
description: >-
  Use when tickets are ready for manual QA, when a build goes to a tester, when
  tickets move to the QA status, when writing "How to test" steps, or when a
  tester's results come back.
---

# QA hand-off

A tester needs three things and nothing else: a build, a "How to test" per ticket, and one build note. They never have to read an MR. Wrong steps cost a full round, so every line must match what the code does.

## Who does what

- **A research worker drafts** every "How to test" and the build note. It reads each ticket (acceptance criteria, comments), its MR (description, "Decisions made", review threads) and the walkthrough. The `research` profile can't write files, so it sends the drafts by message or names a file in its scratchpad. The coordinator saves them to `.evidence/<task>/`.
- **The coordinator posts** the comments, moves the tickets and sends the note, as the workspace's standing rules allow.

## "How to test", per ticket

Shape (`${CLAUDE_SKILL_DIR}/references/how-to-test.md`): the build and platform, the account to use, 3–6 plain steps ("do this, see that") from the acceptance criteria, then out of scope and known limits.

- **Ticket and MR differ:** the MR's decisions win, because what reviewers agreed overrides the ticket text. List every difference for the coordinator, and write the steps the way the code behaves.
- **Shared test accounts:** name the account, never a password. Write each limit as "never <X> on the shared account": delete it, change its email or password, accept a legal document, finish a one-time test. Where the account lacks data (an empty history, no pending document), say what QA will see instead (the empty state) and what account would show the full screen.
- **Claims about another app or the old version:** checked (`file:line`, or seen on a device), or left out.
- Short sentences, plain words. No internal paths, agent names or tool names.

## Moving tickets

- Post "How to test" (and the evidence comment, if the workspace keeps QA evidence), then move the ticket to the QA status. Never the move alone.
- Look the transition up by the target status name, never by a hard-coded id, because ids differ per issue type.
- A ticket with nothing for manual QA (CI-only checks, tooling) goes to Done with its sign-off comment instead.

## The build note

One new top-level message in the team's QA channel, not a reply in an old thread, with the artifact attached and the tester tagged. At most 8 lines: build number and commit, the tickets (key and short name), the accounts line, the known limits, what is experimental ("try it, tell us what looks off"), and which platform follows later. A build from an integration branch (skill `integration-build`) also says which MR heads it contains.

If every chat send asks the human for an approval click (an organization policy on the chat connector), send it as one message, and tell the human before you send.

## Results

- Pass: the coordinator moves the ticket to Done (or what the workspace says) without asking.
- Fail: a comment with the build, the steps and a screenshot or video, and the ticket goes back to In Progress.
- Something new: its own bug ticket, linked.

## Red flags

| Thought | Do instead |
|---|---|
| "The ticket says it, so the steps say it" | Read the MR's decisions. The MR wins, and the difference is listed. |
| "Move the tickets now, the steps can follow" | Steps first, or with the move. |
| "QA can try deleting the account on the shared one" | Never. A disposable account, or out of scope. |
| "Five tickets, five messages" | One build note. |
