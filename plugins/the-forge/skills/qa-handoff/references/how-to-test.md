# How to test: templates

## Per ticket (one tracker comment each)

```markdown
**How to test** (QA build <BUILD>, <platform>)

Account: <the shared test account, by name or email only | "your own test account">.

1. <Open / tap / type …>. You see <…>.
2. <…>
3. <…>

Out of scope / known limits:
- <Something the ticket mentions that this build doesn't do, and where it went (ticket key)>.
- Never <delete the account | change its email or password | accept a legal document | finish a test> on the shared account.
- <What the shared account can't show, and what you see instead, e.g. "it has no past orders, so the history shows the empty state">.
```

## Differences for the coordinator (not posted)

```markdown
- <ticket> AC <n>: the ticket says <…>; the MR does <…> ("Decisions made" / review thread <id>). Steps follow the MR.
```

## Build note (one chat message, artifact attached)

```markdown
<@tester> new QA build <BUILD> (<commit>) of <app>, <platform>: <what's in it, one line>.
- <KEY> <short name>
- <KEY> <short name>
Accounts: <which account for what>. Limits: <one line>.
Experimental: <feature>: try it, tell us what looks off.
<Platform> follows when <reason>.
```
