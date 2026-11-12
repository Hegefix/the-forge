# The qa-run config

Lives at `.claude/qa-run.json` in the project. Start from `${CLAUDE_SKILL_DIR}/templates/qa-run.json`. The skill never stores passwords or tokens here.

| Key | Meaning |
|---|---|
| `app.ios_bundle_id`, `app.android_package` | Ids for `simctl launch`, `adb` and Maestro's `appId`. |
| `builds.*` | Where each build comes from, in words, so the skill can tell the tester where to look. `folder` is where downloaded builds go. |
| `flows.dir`, `flows.repo` | Maestro flows. `run-flows.sh` takes the folder as an argument. |
| `flows.smoke`, `flows.regression` | Flow names for "regression on build X" and the first check after install. |
| `sign_in_command` | Run after install, with `--device <id>` appended. It must read credentials from a file outside the repo and never print them. Empty: the tester signs in by hand. |
| `devices.*` | Simulator and AVD names as `xcrun simctl list devices` and `emulator -list-avds` show them. API levels map to AVD names. |
| `evidence_dir` | One folder per ticket below it. |
| `tracker.*` | Ticket key prefix, and any label that means "no manual QA". |
| `test_accounts` | Names and limits of shared accounts. See `qa-handoff` for what to forbid on them. |

`bash ${CLAUDE_SKILL_DIR}/scripts/preflight.sh` reports every key that is still a `<placeholder>`.
