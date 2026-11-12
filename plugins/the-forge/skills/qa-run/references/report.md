# Report and draft comment

## `report.md`, one per ticket

```
# <KEY> – <ticket title>
Build: <number or commit> · Tested: <date> · Tester: <name from the tester>

| Criterion | Device | Result | What I saw | Evidence |
|---|---|---|---|---|
| <criterion in the ticket's words> | iPhone sim, iOS <v> | PASS | <one line> | <KEY>-ac1-iphone.png |
| <criterion> | Android tablet, API <n> | FAIL | Step 3: tapped "Save"; expected a toast, saw nothing | <KEY>-ac2-tablet.mp4 |
| <criterion> | iPhone sim | BLOCKED | Only a TestFlight build, no simulator app | – |

Not covered: <anything the ticket asks that was out of scope or had no way to test>
Notes: <differences from design, side findings; each could be its own ticket>
```

Results: `PASS` (saw the expected result), `FAIL` (saw something else), `BLOCKED` (could not do the step; say why and what unblocks it). One row per criterion and device.

## Draft Jira comment

Plain English, at most 12 lines, no tool or agent names. Start with the verdict.

```
Tested on build <number> (<date>).
Result: PASS / FAIL / PARTIAL.
Devices: iPhone <model/iOS>, Pixel <model/API>.
- AC1: pass
- AC2: fail. <step, expected, seen>
- AC3: not tested, <reason>
Evidence: <files attached>.
Other findings: <one line each, or none>.
```

A FAIL always carries the build, the steps and a screenshot or video, as `qa-handoff` asks. A new problem outside the ticket is a separate finding for the tester to raise as its own ticket, not a line that hides in this comment.
