---
name: meeting-prep
description: >-
  Use when the human has a meeting with another team or a stakeholder and needs facts
  and talking points, when proposals or tickets have to be drafted for another team's
  board, or when work is planned in a repo another team owns.
---

# Meeting prep

Two outputs, both drafts for the human: one page of facts with sources and five lines to say, and, when the meeting is about work for another team, ticket drafts in that team's own format. Nothing is created, posted or assigned before the human's OK.

## The page

- **A research worker gathers the facts.** Every fact has a source: `file:line`, a ticket key with its status, a version with its date, a decision-log line. What it couldn't confirm is marked "not confirmed", never guessed.
- **The `research` profile can't write files,** so the worker sends the page by message or names a file in its scratchpad. The coordinator saves it to `.evidence/<topic>/`.
- **Shape** (`${CLAUDE_SKILL_DIR}/references/templates.md`): context in two lines, the facts, the options with a recommendation, questions for the other side, and five lines the human can say.
- **Short and plain:** the human reads it minutes before the call.

## Ticket drafts for another team's board

- **Read 2–3 of their recent tickets first** and copy their exact shape: sections, type, parent or epic, labels, components, team field, how they name and size work, which sprint new work goes to. Use their words.
- **Read their repo's contributing rules** before proposing work there. Some forbid AI co-author trailers in commits, need their own ticket key in branch names, or take MRs into a branch other than the default. Every later worker brief for that repo repeats those rules.
- **Per draft:** summary, fields, the body in their shape, links. Sprint and assignee are proposals.
- **End with "Also ask in the call":** assignments, order changes, duplicate tickets on our side that could close.

## After the human's OK

- Create exactly the drafts the human approved, as approved. An OK on a list is not an OK on side steps.
- After the meeting, update the drafts and the page with what was agreed, and log the decisions.

## Red flags

| Thought | Do instead |
|---|---|
| "I'll create the tickets so they're ready for the call" | Drafts only. New tickets are visible to others. |
| "Our ticket template is good enough" | Their format, copied from their tickets. |
| "The version is probably the latest" | Look it up, with the date and source. |
| "The worker's write was blocked, so there is no page" | It sends the page by message; you save it. |
