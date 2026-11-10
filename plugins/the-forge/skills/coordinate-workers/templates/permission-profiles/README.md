# Worker permission profiles

A profile is a Claude Code settings file with only `permissions.deny` rules. `launch-worker.sh --profile <name>` passes it to the worker as `claude --settings <file>`, and the comms watcher's and the scribe's `pass.py` build each headless pass's settings from `watcher.json`. The rules add to the user's own settings. A deny rule beats any allow rule and every permission mode, `auto` and `bypassPermissions` included. So the brief's "no chat, no merge" is enforced, not only requested.

| Profile | For | Blocks |
|---|---|---|
| `research` | reading code and docs, analysis, a write-up returned by message | external communication, git hosting actions, devices, and every write: `Edit`, `Write`, `NotebookEdit`, `git commit`, `git push`, creating or editing PRs/MRs, `gh api` and `glab api` |
| `code` | a task in its own worktree: commits, its own branch, a Draft PR/MR, CI | external communication, git hosting actions, devices |
| `device` | like `code`, plus simulators, emulators and device tests, after the coordinator's "go" | external communication, git hosting actions |
| `browser` | web pages in the human's signed-in browser, such as developer portals, store consoles and CI web pages; started with `--chrome` | the same as `code`, except that the browser stays open; plus file edits (`Write` stays, for notes), commits, pushes, creating or editing PRs/MRs, `gh api` and `glab api`, and every device command |
| `watcher` | the headless passes of the comms watcher and the scribe, which only read (the scribe also writes its notes) | the same as `code`, except that chat and mail stay readable; plus edits in repos, worktrees and coordination files, commits, pushes, creating or editing PRs/MRs, and `gh api`/`glab api` writes |

## Profiles vs the classifier

Deny rules are hard limits. They are not the only check. In `auto` mode, a classifier judges every tool call that no allow rule covers, and it can block a call the profile allows. A profile only denies, so it never allows anything.

The usual case: a worker with the `code` profile may push its own branch and open a Draft PR/MR, but the classifier still blocks `git push` and `glab mr create` as outward-facing. The worker reports `BLOCKED by permission`, and nothing moves until the human clicks. Expect several blocks a day.

The fix is allow rules in the human's own `~/.claude/settings.json`, not in a profile:

```json
{
  "permissions": {
    "allow": [
      "Bash(git push origin:*)",
      "Bash(git push -u origin:*)",
      "Bash(git push)",
      "Bash(glab mr create:*)",
      "Bash(glab mr update:*)"
    ],
    "deny": [
      "Bash(git push * main)",
      "Bash(git push *:main)",
      "Bash(git push * main *)",
      "Bash(git push * --force*)",
      "Bash(git push -f*)",
      "Bash(git push * -f*)"
    ]
  }
}
```

Use `gh pr create:*` and `gh pr edit:*` instead of the `glab` lines if you use GitHub. Change `main` if your default branch has another name. Merge these lists into the rules you already have.

- The allow rules cover only the worker's own branch and a Draft PR/MR. The deny rules are the guard: no push to the default branch, no force push. A deny rule beats an allow rule.
- A deny on a push to `main` also stops your own direct pushes to `main` from these sessions. Kit and workspace changes then go through a branch and a PR.
- Keep the classifier for everything else, above all chat sends and anything else other people see. Don't add allow rules for those.
- The coordinator must not add these rules itself. The classifier blocks a session that edits its own permissions, on purpose. The coordinator writes a small script that adds the rules, and the human reads it and runs it.
- Check on a new machine: `/permissions` lists the rules in force. If a worker's push or Draft PR/MR is blocked anyway, the allow rules are missing there.

## The blocks

The five files share these blocks, in this order:

- **External communication (MCP servers):**
  - `mcp__<chat-server>`, `mcp__<mail-server>`, `mcp__<browser-server>`: every tool of that server. The browser acts as the human, with their logins. `browser.json` leaves the browser server out, and `watcher.json` blocks only the chat and mail servers' write tools, one line per tool (`mcp__<chat-server>__<chat-write-tool>`, and `mcp__<mail-server>__outlook_send_mail` and the rest), because the comms watcher reads both. If it doesn't read mail, deny the whole mail server there too.
  - `mcp__<tracker-server>__create*`, `update*`, `edit*`, `add*`, `transition*`, `delete*`: the issue tracker's and wiki's write tools. Its read tools stay allowed.
- **Git hosting actions:** merge, approve or review, close, comment, issue create and comment, release, and CI or workflow runs, for both `gh` and `glab`; force pushes; pushes to `main`.
- **Devices** (optional): `xcrun simctl boot`, `emulator`, and `<device-test-runner>`, the command that runs your tests on a device or simulator. `device.json` leaves this block out, and `browser.json` blocks all of `xcrun simctl` and `adb` too.
- **Read only** (`research.json`, and `browser.json` without `Write`): the writes listed in the table. `gh api` and `glab api` are blocked whole, because `-f`, `-F` and `--input` turn a request into a POST without `-X`. To read a PR/MR, use `gh pr view` or `glab mr view`.
- **Watcher** (`watcher.json` only): helpers need `gh api`/`glab api` GET requests (open MRs across projects, approvals), so only the flags that make a write are blocked: `-X`, `--method`, `-f`, `-F`, `--field`, `--raw-field`, `--input` and, for `glab`, `--form`, each as the first argument and later in the command. Edits are blocked in the workspace `CLAUDE.md`, the worktrees, each repo, the decision log, the profiles and `coordination/tools/` (the helpers' own instructions and scripts). Plus `git commit`, `git push`, and creating or editing PRs/MRs. A headless pass also runs with `--permission-mode dontAsk` and an allowlist (the helpers' README says which tools), so the profile is the second layer: the pass has no Bash, `pass.py` writes the state files, the scribe writes only its notes, and the notes repo is pushed only by `push.sh`, which `pass.py` runs.

## Fill them in

1. Copy the five files to the workspace: `coordination/permission-profiles/`. `--profile <name>` and the helpers' `pass.py` look there.
2. Replace every `<placeholder>` with your MCP server names. Every MCP tool is named `mcp__<server>__<tool>`, so the coordinator can read the names off its own tool list, and `/mcp` lists the servers. Names look like this:
   - a claude.ai connector: `mcp__claude_ai_<Name>`, with spaces as `_`;
   - a plugin's server: `mcp__plugin_<plugin>_<server>`;
   - a server from your own MCP config: `mcp__<server>`.

   The same service can come from two places, such as a connector and a plugin. Add a line for each name (see "One service, several names" below). Delete the lines for services you don't use.
   - `watcher.json`: replace `<chat-write-tool>` with one line per write tool of your chat server: whatever sends, schedules, reacts, uploads, or creates or updates canvases, lists and channels. For the Slack connector, that is `slack_send_message`, `slack_send_message_draft`, `slack_schedule_message`, `slack_add_reaction`, `slack_create_canvas`, `slack_update_canvas`, `slack_get_file_upload_url`, `slack_complete_file_upload`, `slack_create_conversation`, `slack_create_list`, `slack_update_list`, `slack_add_list_record` and `slack_update_list_record`. Check your own tool list, because servers add tools.
   - `watcher.json`: the `mcp__<mail-server>__…` lines are the Microsoft 365 connector's write tools: the ones that send, draft, reply to, forward, delete, trash or label mail, or change filters, calendar events or the vacation reply, and, because that server also holds Teams and SharePoint, the ones that send Teams messages or change SharePoint files. For another mail server, replace them with its own tools that do any of that, one line each. Either way, check your own tool list, because servers add tools.
   - `watcher.json`: replace `<workspace>` with the workspace's absolute path without its leading `/`, because `//` already starts the path at the filesystem root (`/Users/me/work` gives `Edit(//Users/me/work/CLAUDE.md)`). Add one `<repo-dir>` line per repo folder in the workspace.
3. Check the tool names of your tracker. If its write tools don't start with `create`, `update`, `edit`, `add`, `transition` or `delete`, add lines for them.
4. No devices: delete the device lines from `research.json`, `code.json`, `browser.json` and `watcher.json`. Your default branch isn't `main`: change the four `main` rules in each file.
5. Add what else your workers must not do, such as a deploy CLI.
6. Device work blocked by the permission mode's classifier, not by a rule (for example a clean native rebuild or killing an emulator flagged as "interfering with workloads")? Add `permissions.allow` rules for those exact commands to `device.json`, the one profile that may hold allow rules, such as `Bash(xcrun simctl shutdown:*)`. Rules match the start of the command, so run them as written (`./gradlew …` from inside `android/`, not `cd android && …`). The coordinator also puts the device "go" into the starting brief, not only in a later message.

**One service, several names.** A chat or mail service can be connected more than once: as a claude.ai connector (`mcp__claude_ai_Slack`) and as a plugin's server (`mcp__plugin_<plugin>_slack`), for example when a plugin brings its own. To the rules these are two servers. A profile that denies one name leaves the other open with all its write tools, and when one connection drops or a plugin is installed later, workers use the other one without anyone noticing. We found exactly that: every profile denied the connector, while the plugin's Slack server, the one actually loaded, could send messages. So every profile denies every name of every service it blocks (`watcher.json`: the write tools under each name). Check `/mcp` after you add a plugin or a connector, and add any new name to all five files. The helpers' `config.json` takes a list of server names for the same reason.

A line with a `<placeholder>` left in it matches nothing, so that service stays open. That is why `launch-worker.sh`, the helpers' `start-headless.sh` and their `pass.py` refuse a profile that still has one, or that isn't valid JSON with a `permissions.deny` list.

**Keep the files strict JSON.** With a `//` comment in it, Claude Code ignores the whole file, prints no error in a headless run, and blocks nothing. That is why the notes are here and not in the JSON.

## The browser profile

The browser tools load only when Claude Code starts with `--chrome`, so `launch-worker.sh` adds it for a profile file named `browser.json`, and for no other. The profile can't limit what the worker clicks: the browser is signed in as the human everywhere. So the brief names the sites and the exact actions, and the skill `browser-worker` holds the rules: the human signs in; no passwords, codes or keys; no messages, purchases, deletions, terms or user changes unless the brief quotes them. One browser worker at a time, because there is one browser.

`Write` stays allowed, so the worker can keep notes and evidence files; `Edit` is denied, so it doesn't change code.

## Check a profile

Run it headless in a throwaway repo with no remote:

```bash
claude -p "Run: gh pr merge 1" --settings code.json --allowedTools Bash \
  --output-format stream-json --verbose
```

- The first line (`"subtype":"init"`) lists the session's tools. A denied MCP server or tool is not in that list, so the worker never sees it.
- A denied Bash command comes back as `Permission to use Bash with command … has been denied.`, and the last line lists it in `permission_denials`. `--allowedTools Bash` makes every other command run without a prompt, so a denial there comes from the profile.
- In an interactive session, `/permissions` lists the rules in force.

## Limits

These are guardrails, not a sandbox.

- Bash can still write files (`echo … > file`), also in `research`.
- Rules match the command text. `*` matches any characters, and a rule ending in `:*` matches by prefix. Claude Code checks each part of `a && b`. But a different command with the same effect passes: `git push origin +main` forces without `--force`, `gh api` can merge in `code`, and a plain `git push` goes wherever the branch's upstream points. (`launch-worker.sh` creates branches with no upstream.)
- MCP rules match server names. A new server, or the same service under another name (a connector and a plugin's server), is not covered until you add it to every profile.
- So the permission mode or classifier, the brief and the worker's own rules still matter.
