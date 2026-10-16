# Worker permission profiles

A profile is a Claude Code settings file with only `permissions.deny` rules. `launch-worker.sh --profile <name>` passes it to the worker as `claude --settings <file>`, and the helpers' `start.sh` scripts pass `watcher.json` the same way. The rules add to the user's own settings. A deny rule beats any allow rule and every permission mode, `auto` and `bypassPermissions` included. So the brief's "no chat, no merge" is enforced, not only requested.

| Profile | For | Blocks |
|---|---|---|
| `research` | reading code and docs, analysis, a write-up returned by message | external communication, git hosting actions, devices, and every write: `Edit`, `Write`, `NotebookEdit`, `git commit`, `git push`, creating or editing PRs/MRs, `gh api` and `glab api` |
| `code` | a task in its own worktree: commits, its own branch, a Draft PR/MR, CI | external communication, git hosting actions, devices |
| `device` | like `code`, plus simulators, emulators and device tests, after the coordinator's "go" | external communication, git hosting actions |
| `watcher` | helpers that run on a loop and only read: the comms watcher and the scribe | the same as `code`, except that chat stays readable; plus edits in repos, worktrees and coordination files, commits, pushes, creating or editing PRs/MRs, and `gh api`/`glab api` writes |

## The blocks

The four files share these blocks, in this order:

- **External communication (MCP servers):**
  - `mcp__<chat-server>`, `mcp__<mail-server>`, `mcp__<browser-server>`: every tool of that server. The browser acts as the human, with their logins. `watcher.json` blocks only the chat server's write tools (`mcp__<chat-server>__<chat-write-tool>`), because the comms watcher reads chat.
  - `mcp__<tracker-server>__create*`, `update*`, `edit*`, `add*`, `transition*`, `delete*`: the issue tracker's and wiki's write tools. Its read tools stay allowed.
- **Git hosting actions:** merge, approve or review, close, comment, issue create and comment, release, and CI or workflow runs, for both `gh` and `glab`; force pushes; pushes to `main`.
- **Devices** (optional): `xcrun simctl boot`, `emulator`, and `<device-test-runner>`, the command that runs your tests on a device or simulator. `device.json` leaves this block out.
- **Read only** (`research.json` only): the writes listed in the table. `gh api` and `glab api` are blocked whole, because `-f`, `-F` and `--input` turn a request into a POST without `-X`. To read a PR/MR, use `gh pr view` or `glab mr view`.
- **Watcher** (`watcher.json` only): helpers need `gh api`/`glab api` GET requests (open MRs across projects, approvals), so only the flags that make a write are blocked: `-X`, `--method`, `-f`, `-F`, `--field`, `--raw-field`, `--input` and, for `glab`, `--form`, each as the first argument and later in the command. Edits are blocked in the workspace `CLAUDE.md`, the worktrees, each repo, the decision log, the profiles and `coordination/tools/` (the helpers' own instructions and scripts). The helpers write their state files with Bash, and the scribe writes the notes. Plus `git commit`, `git push`, and creating or editing PRs/MRs. The scribe pushes the notes repo only through its own `push.sh`.

## Fill them in

1. Copy the four files to the workspace: `coordination/permission-profiles/`. `--profile <name>` and the helpers' `start.sh` look there.
2. Replace every `<placeholder>` with your MCP server names. Every MCP tool is named `mcp__<server>__<tool>`, so the coordinator can read the names off its own tool list, and `/mcp` lists the servers. Names look like this:
   - a claude.ai connector: `mcp__claude_ai_<Name>`, with spaces as `_`;
   - a plugin's server: `mcp__plugin_<plugin>_<server>`;
   - a server from your own MCP config: `mcp__<server>`.

   The same service can come from two places, such as a connector and a plugin. Add a line for each name. Delete the lines for services you don't use.
   - `watcher.json`: replace `<chat-write-tool>` with one line per write tool of your chat server: whatever sends, schedules, reacts, uploads, or creates or updates canvases, lists and channels. For the Slack connector, that is `slack_send_message`, `slack_send_message_draft`, `slack_schedule_message`, `slack_add_reaction`, `slack_create_canvas`, `slack_update_canvas`, `slack_get_file_upload_url`, `slack_complete_file_upload`, `slack_create_conversation`, `slack_create_list`, `slack_update_list`, `slack_add_list_record` and `slack_update_list_record`. Check your own tool list, because servers add tools.
   - `watcher.json`: replace `<workspace>` with the workspace's absolute path without its leading `/`, because `//` already starts the path at the filesystem root (`/Users/me/work` gives `Edit(//Users/me/work/CLAUDE.md)`). Add one `<repo-dir>` line per repo folder in the workspace.
3. Check the tool names of your tracker. If its write tools don't start with `create`, `update`, `edit`, `add`, `transition` or `delete`, add lines for them.
4. No devices: delete the device lines from `research.json`, `code.json` and `watcher.json`. Your default branch isn't `main`: change the four `main` rules.
5. Add what else your workers must not do, such as a deploy CLI.
6. Device work blocked by the permission mode's classifier, not by a rule (for example a clean native rebuild or killing an emulator flagged as "interfering with workloads")? Add `permissions.allow` rules for those exact commands to `device.json`, the one profile that may hold allow rules, such as `Bash(xcrun simctl shutdown:*)`. Rules match the start of the command, so run them as written (`./gradlew …` from inside `android/`, not `cd android && …`). The coordinator also puts the device "go" into the starting brief, not only in a later message.

A line with a `<placeholder>` left in it matches nothing, so that service stays open. That is why `launch-worker.sh` and the helpers' `start.sh` refuse a profile that still has one, or that isn't valid JSON with a `permissions.deny` list.

**Keep the files strict JSON.** With a `//` comment in it, Claude Code ignores the whole file, prints no error in a headless run, and blocks nothing. That is why the notes are here and not in the JSON.

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
- MCP rules match server names. A new server, or a server under another name, is not covered until you add it.
- So the permission mode or classifier, the brief and the worker's own rules still matter.
