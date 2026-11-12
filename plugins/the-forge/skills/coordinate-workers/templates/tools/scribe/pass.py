#!/usr/bin/env python3
"""One scribe pass. loop.sh runs it every interval_min (config.json).

  python3 -I pass.py                 one pass now (to try it on a copy of the state: STATE_DIR=state-test …)
  SCRIBE_DRY_RUN=1 python3 -I pass.py  a pass that reads everything but can't write notes; cursor and inbox kept, no
                                       notices (it prints them)
  python3 -I pass.py --interval      seconds between gate checks, from config.json
  python3 -I pass.py --self-check    its tests: passes in a throwaway workspace with a stub claude

1. Gate, no model: if the decision log has no new lines and state/inbox/ is empty, log "no news" and stop.
2. Builds the prompt: PASS.md + "This workspace" (from config.json) + the notes' rules file, if one is set, as
   the system prompt file; the new log lines, inbox notes, changed evidence files and the other helpers' new log
   lines as the first message.
3. Runs ONE headless `claude -p` with an empty context. Only the tools in allowed_tools() can run
   (--permission-mode dontAsk + --allowedTools); watcher.json's deny rules still apply. No shell. Writes go to
   the notes only: Edit/Write limited to the notes' paths, or the notes MCP server's write tools.
4. Then: moves the handled inbox notes to inbox/done/, writes notices for the coordinator to state/notices/
   (the comms watcher's wait_digest.py on that folder wakes the coordinator), runs push.sh when notes changed and
   a notes repo is set, and writes runs.log and the cursor. A failed pass goes to errors.log and keeps the cursor
   and the inbox.

Environment: WORKSPACE (default: three folders up, the folder that holds coordination/), STATE_DIR (default:
state/ here), CLAUDE_BIN (default: claude on PATH), SCRIBE_CONFIG (default: config.json here).
"""
import contextlib, fcntl, glob, io, json, os, re, shutil, signal, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.abspath(os.environ.get("WORKSPACE") or os.path.join(HERE, "..", "..", ".."))
STATE = os.path.abspath(os.environ.get("STATE_DIR") or os.path.join(HERE, "state"))
CONFIG = os.environ.get("SCRIBE_CONFIG") or os.path.join(HERE, "config.json")
PROFILE = os.path.join(WORKSPACE, "coordination", "permission-profiles", "watcher.json")
PUSH = os.path.join(HERE, "push.sh")
CLAUDE = os.environ.get("CLAUDE_BIN") or "claude"
DRY = os.environ.get("SCRIBE_DRY_RUN") == "1"  # writes off, push off, cursor and inbox kept
ALERT_AFTER = 3  # failures in a row before a notice says so
PLACEHOLDER = re.compile(r"<[A-Za-z][^<>\"]*>")
TZ = None  # set from config.json; None = this machine's local time zone

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["notes_updated", "notes_created", "inbox_handled", "notices", "summary"],
    "properties": {
        "notes_updated": {"type": "array", "items": {"type": "string"}},
        "notes_created": {"type": "array", "items": {"type": "string"}},
        "inbox_handled": {"type": "array", "items": {"type": "string"}},
        "notices": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"}}}


def load_config(strict=True):
    with open(CONFIG) as f:
        text = f.read()
    cfg = json.loads(text)
    if strict and PLACEHOLDER.search(text):
        raise ValueError(f"{CONFIG} still has a placeholder: {PLACEHOLDER.search(text).group(0)}")
    return cfg


def p(*name):
    return os.path.join(STATE, *name)


def ws(rel):
    return os.path.normpath(os.path.join(WORKSPACE, os.path.expanduser(rel)))


def local(dt, fmt="%Y-%m-%d %H:%M"):
    return dt.astimezone(TZ).strftime(fmt)


def write_atomic(path, text):
    tmp = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".tmp")
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def append(name, line):
    with open(p(name), "a") as f:
        f.write(line.rstrip("\n") + "\n")


def clean(s, n=None):
    s = " ".join(str(s or "").replace("|", "/").split())
    return s if n is None or len(s) <= n else s[: n - 1] + "…"


def notice(lines, now):
    """A file for the coordinator; its waiter (comms-watch/wait_digest.py on state/notices/) prints it."""
    os.makedirs(p("notices"), exist_ok=True)
    name = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".md"
    write_atomic(p("notices", name), "".join(f"scribe: {clean(x, 400)}\n" for x in lines))


def notes_files(cfg):
    """Plain-file notes: the notes folder, and the handover note, dashboard and app flows note it may write."""
    n = cfg["notes"]
    folder = [ws(n["dir"])] if n.get("dir") else []
    files = [ws(n[k]) for k in ("handover", "dashboard", "app_flows") if n.get(k)]
    return folder, [f for f in files if not any(f.startswith(d + os.sep) for d in folder)]


def plugin_names():
    """Every plugin that could load, so the pass can switch them off (no skills, hooks or extra MCP)."""
    names = set()
    home = os.path.expanduser("~/.claude")
    for path, key in ((os.path.join(home, "plugins", "installed_plugins.json"), "plugins"),
                      (os.path.join(home, "settings.json"), "enabledPlugins")):
        try:
            with open(path) as f:
                names |= set(json.load(f).get(key) or {})
        except Exception:  # noqa: BLE001 - a missing or odd file only means fewer plugins to switch off
            pass
    for d in glob.glob(os.path.join(home, "plugins", "synced", "*", "*")):
        if os.path.isdir(d):
            names.add(os.path.basename(d).split("~")[0] + "@synced")
    return sorted(names)


def plugin_switches(cfg):
    """enabledPlugins for a pass: every plugin off, except the plugins whose MCP servers the notes or the tracker
    use (plugin_<plugin>_<server>), because a plugin switched off also stops its servers. Such a server that no
    installed plugin provides would never connect: ValueError with what to fix."""
    names = plugin_names()
    on = set()
    for what, srv in (("notes", cfg["notes"].get("server") if cfg["notes"].get("kind") == "mcp" else None),
                      ("tracker", (cfg.get("tracker") or {}).get("server"))):
        if not (srv or "").startswith("plugin_"):
            continue
        found = {n for n in names if srv.startswith(f"plugin_{n.split('@')[0]}_")}
        if not found:
            raise ValueError(f"config.json: the {what} server {srv} is a plugin server, and no installed plugin "
                             "provides it: install the plugin, or use the service's other server")
        on |= found
    return {n: n in on for n in names}


def build_settings(cfg, plugins):
    with open(PROFILE) as f:
        s = json.load(f)  # a broken profile stops the pass here: fail closed, never run without it
    if PLACEHOLDER.search(json.dumps(s)):
        raise ValueError("watcher.json still has a <placeholder>")
    n = cfg["notes"]
    deny = s.setdefault("permissions", {}).setdefault("deny", [])
    deny += ["mcp__" + x for x in cfg.get("deny_servers") or []]
    if n.get("kind") == "mcp":
        deny += [f"mcp__{n['server']}__{t}" for t in n.get("never_tools") or []]
        if DRY:
            deny += [f"mcp__{n['server']}__{t}" for t in n.get("write_tools") or []]
    elif DRY:
        deny += ["Edit", "Write"]
    s["disableAllHooks"] = True
    s["claudeMdExcludes"] = ["**/CLAUDE.md", "**/CLAUDE.local.md", "**/AGENTS.md"]
    s["enabledPlugins"] = plugins
    s["autoMemoryEnabled"] = False
    path = p(".pass-settings.json")
    write_atomic(path, json.dumps(s, indent=1))
    return path


def allowed_tools(cfg):
    n = cfg["notes"]
    read_dirs = [os.path.dirname(ws(cfg.get("decision_log") or "coordination/decision-log.md")),
                 ws(cfg.get("evidence_dir") or ".evidence")]
    out = [f"{t}(/{d}/**)" for t in ("Read", "Grep", "Glob") for d in read_dirs]
    if n.get("kind") == "mcp":
        out += [f"mcp__{n['server']}__{t}" for t in (n.get("read_tools") or [])
                + ([] if DRY else n.get("write_tools") or [])]
    else:
        folder, files = notes_files(cfg)
        out += [f"{t}(/{d}/**)" for t in ("Read", "Grep", "Glob") for d in folder]
        out += [f"Read(/{f})" for f in files]
        if not DRY:
            out += [f"{t}(/{d}/**)" for t in ("Edit", "Write") for d in folder]
            out += [f"{t}(/{f})" for t in ("Edit", "Write") for f in files]
    tr = cfg.get("tracker") or {}
    if tr.get("server"):
        out += [f"mcp__{tr['server']}__{t}" for t in tr.get("tools") or []]
    return out


def tools_flag(cfg):
    return "ToolSearch,Read,Grep,Glob" + (",Edit,Write" if cfg["notes"].get("kind") != "mcp" and not DRY else "")


def system_prompt(cfg):
    """PASS.md + "This workspace" + the notes' rules file. The same text every pass, so the cache holds it."""
    n = cfg["notes"]
    with open(os.path.join(HERE, "PASS.md")) as f:
        text = f.read()
    lines = ["", "## This workspace", ""]
    if n.get("kind") == "mcp":
        lines += [f"- Notes: the MCP server `{n['server']}`. Read with {', '.join(n.get('read_tools') or []) or '-'};"
                  f" write with {', '.join(n.get('write_tools') or []) or '-'}.",
                  f"- Folders you may write in: {', '.join(n.get('folders') or []) or 'any'}."]
    else:
        lines.append(f"- Notes: plain files in `{ws(n['dir'])}` (Read, Edit and Write there)." if n.get("dir")
                     else "- Notes: no notes folder; only the files below.")
    for key, label in (("handover", "Handover note"), ("dashboard", "Dashboard"), ("app_flows", "App flows")):
        if n.get(key):
            lines.append(f"- {label}: `{n[key] if n.get('kind') == 'mcp' else ws(n[key])}`")
    lines.append(f"- Decision log: `{ws(cfg.get('decision_log') or 'coordination/decision-log.md')}` (read only)")
    lines.append(f"- Evidence: `{ws(cfg.get('evidence_dir') or '.evidence')}` (read only)")
    tr = cfg.get("tracker") or {}
    lines.append(f"- Tracker (read only): {', '.join(tr.get('tools') or []) or '-'}" if tr.get("server")
                 else "- Tracker: none")
    text += "\n".join(lines) + "\n"
    if n.get("rules_file"):
        found = sorted(glob.glob(os.path.expanduser(n["rules_file"])))
        text += "\n## The notes' rules\n\n" + (open(found[-1]).read() if found else
                                               f"(The rules file {n['rules_file']} was not found.)\n")
    path = p(".pass-system.md")
    write_atomic(path, text)
    return path


def tail_from(path, offset, keep=None, limit=40):
    """New lines of a growing file since a byte offset (None: from its end); returns (lines, new offset).
    A file now smaller than the offset was rewritten or rotated: it is read from its start."""
    try:
        size = os.path.getsize(path)
        if offset is None:
            return [], size
        with open(path, "rb") as f:
            f.seek(offset if 0 <= offset <= size else 0)
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return [], offset
    lines = [x for x in data.splitlines() if x.strip() and (keep is None or keep(x))]
    return lines[-limit:], size


def changed_evidence(folder, since, limit=60):
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "build", "ios", "android")]
        for f in files:
            path = os.path.join(root, f)
            try:
                m = os.path.getmtime(path)
            except OSError:
                continue
            if m > since.timestamp():
                out.append((m, os.path.relpath(path, WORKSPACE)))
    out.sort(reverse=True)
    return [f"- {local(datetime.fromtimestamp(m, timezone.utc))} {rel}" for m, rel in out[:limit]], len(out)


def run_claude(cfg, settings, system_file, user_text, trace):
    cmd = [CLAUDE, "-p", "--model", cfg.get("model") or "sonnet", "--settings", settings,
           "--permission-mode", "dontAsk", "--permission-prompts", "none",
           "--allowedTools", ",".join(allowed_tools(cfg)), "--tools", tools_flag(cfg),
           "--disable-slash-commands", "--exclude-dynamic-system-prompt-sections",
           "--no-session-persistence", "--max-budget-usd", str(cfg.get("max_usd") or 3),
           "--json-schema", json.dumps(SCHEMA), "--append-system-prompt-file", system_file,
           "--output-format", "stream-json", "--verbose"]
    timeout = int(cfg.get("timeout_s") or 600)
    with open(trace, "w") as out, open(p(".pass-stderr.txt"), "w") as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=HERE,
                                text=True, start_new_session=True)  # OSError (no claude): the caller's fail()
        try:
            # communicate() ignores a broken pipe: a claude that exits before it reads the first message ends
            # with its exit code and stderr, and the pass fails like any other.
            proc.communicate(user_text, timeout=timeout)
            return proc.returncode
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            return "timeout"


def read_result(trace):
    result, calls = None, {}
    with open(trace) as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "result":
                result = e
            elif e.get("type") == "assistant":
                for b in (e.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        name = b["name"].split("__")[-1]
                        calls[name] = calls.get(name, 0) + 1
    return result, calls


def cost_part(res, cfg):
    if not res:
        return "cost ?"
    u = res.get("usage") or {}
    tin = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    return (f"${res.get('total_cost_usd', 0):.2f} | model {cfg.get('model') or 'sonnet'} | in {tin / 1000:.0f}k (cache read "
            f"{u.get('cache_read_input_tokens', 0) / 1000:.0f}k) out {u.get('output_tokens', 0) / 1000:.1f}k | "
            f"turns {res.get('num_turns', '?')}")


def run_pass(cfg):
    t0 = time.time()
    now = datetime.now(timezone.utc).astimezone(TZ).replace(microsecond=0)
    stamp = local(now)
    with open(ws(cfg.get("decision_log") or "coordination/decision-log.md")) as f:
        log_lines = f.read().splitlines()
    try:
        with open(p("cursor.json")) as f:
            cursor = json.load(f)
    except FileNotFoundError:  # first run: process nothing older
        cursor = {"log_lines": len(log_lines), "since": now.isoformat(),
                  "offsets": {rel: os.path.getsize(ws(rel)) if os.path.exists(ws(rel)) else 0
                              for rel in cfg.get("context_logs") or []}}
        write_atomic(p("cursor.json"), json.dumps(cursor))
    done = int(cursor.get("log_lines", 0))
    if done > len(log_lines):  # the log was cut or rotated: start again from its end
        append("errors.log", f"{stamp} | decision log shrank from {done} to {len(log_lines)} lines; cursor reset")
        done = cursor["log_lines"] = len(log_lines)
        write_atomic(p("cursor.json"), json.dumps(cursor))
    inbox = sorted(f for f in os.listdir(p("inbox")) if not f.startswith(".") and os.path.isfile(p("inbox", f)))

    # The gate: no new log lines and an empty inbox means no model at all.
    if len(log_lines) <= done and not inbox:
        append("runs.log", f"{stamp} | no news")
        return 0

    since = datetime.fromisoformat(cursor["since"])
    upto = min(len(log_lines), done + int(cfg.get("max_log_lines") or 80))
    try:
        with open(p("health.json")) as f:
            health = json.load(f)
    except FileNotFoundError:
        health = {}

    def fail(reason, detail, res=None):
        health["fail_streak"] = health.get("fail_streak", 0) + 1
        append("errors.log", f"{stamp} | {reason} | {clean(detail, 600)} | trace: failed-pass.jsonl")
        append("runs.log", f"{stamp} | FAILED ({reason}) | {time.time() - t0:.0f}s | {cost_part(res, cfg)} | cursor kept")
        if os.path.exists(p("last-pass.jsonl")):
            shutil.copyfile(p("last-pass.jsonl"), p("failed-pass.jsonl"))
        if health["fail_streak"] == ALERT_AFTER:
            notice([f"{ALERT_AFTER} passes failed in a row (last: {reason}: {clean(detail, 200)}); "
                    f"see {p('errors.log')}"], now)
        write_atomic(p("health.json"), json.dumps(health))
        print(f"scribe {stamp}: pass FAILED ({reason})")
        return 1

    try:
        plugins = plugin_switches(cfg)
    except ValueError as e:
        return fail("config", str(e))
    try:
        settings = build_settings(cfg, plugins)
    except Exception as e:  # noqa: BLE001
        return fail("profile", f"{PROFILE}: {e}")
    system_file = system_prompt(cfg)

    offsets, context = dict(cursor.get("offsets") or {}), []
    for rel in cfg.get("context_logs") or []:
        # A log added to config.json later is read from its end: only what comes after goes to the scribe.
        lines, offsets[rel] = tail_from(ws(rel), offsets.get(rel), keep=lambda x: "| noise |" not in x)
        context += [f"### {rel}", ""] + lines + [""] if lines else []
    evidence, n_evidence = changed_evidence(ws(cfg.get("evidence_dir") or ".evidence"), since)
    shas = []
    for repo, ref in (cfg.get("branch_shas") or {}).items():
        try:
            sha = subprocess.run(["git", "-C", ws(repo), "rev-parse", "--short", ref], capture_output=True,
                                 text=True, timeout=20).stdout.strip() or "?"
        except Exception:  # noqa: BLE001
            sha = "?"
        shas.append(f"{repo} {ref} = {sha} (local ref)")

    msg = [f"Run one scribe pass now ({local(now, '%A %Y-%m-%d %H:%M %Z')})."
           + (" DRY RUN: the write tools are off; report what you would change." if DRY else ""),
           f"Last pass: {local(since)}." + (" Default branches: " + "; ".join(shas) + "." if shas else ""), ""]
    if upto > done:
        msg += [f"## New decision-log lines {done + 1}-{upto} of {len(log_lines)}"
                + (" (more wait for the next pass)" if upto < len(log_lines) else ""), ""]
        msg += [f"{i}: {log_lines[i - 1]}" for i in range(done + 1, upto + 1)] + [""]
    if inbox:
        msg += ["## Inbox notes from the coordinator (handle these first)", ""]
        for name in inbox:
            with open(p("inbox", name)) as f:
                msg += [f"### {name}", f.read().strip(), ""]
    msg += [f"## Evidence files changed since the last pass ({n_evidence}; newest {len(evidence)})", ""]
    msg += (evidence or ["- none"]) + ["", "## The other helpers' new log lines (context only, noise left out)", ""]
    msg += context or ["- none"]
    user_text = "\n".join(msg) + "\n"

    trace = p("last-pass.jsonl")
    try:
        rc = run_claude(cfg, settings, system_file, user_text, trace)
    except OSError as e:
        return fail("start", f"{CLAUDE}: {e}")
    res, calls = read_result(trace)
    sid = str((res or {}).get("session_id") or "")
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", sid):
        # Big tool results are spilled to ~/.claude/projects/<cwd>/<session>/tool-results even without session
        # persistence; drop this pass's folder so they don't pile up.
        for d in glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}")):
            shutil.rmtree(d, ignore_errors=True)
    if rc == "timeout":
        return fail("timeout", f"killed after {cfg.get('timeout_s') or 600}s", res)
    if not res:
        with open(p(".pass-stderr.txt")) as f:
            return fail(f"exit {rc}", f.read()[-600:] or "no result event")
    if rc != 0 or res.get("is_error") or not isinstance(res.get("structured_output"), dict):
        return fail(res.get("subtype") or f"exit {rc}", clean(res.get("result"), 400) or "no structured output", res)
    out = res["structured_output"]
    updated, created = out.get("notes_updated") or [], out.get("notes_created") or []
    notices = list(out.get("notices") or [])

    push = "-"
    if not DRY:
        for name in set(out.get("inbox_handled") or []) & set(inbox):
            shutil.move(p("inbox", name), p("inbox", "done", name))
        repo = (cfg["notes"].get("repo") or "").strip()
        if (updated or created) and repo:
            # Plain-file notes: push.sh commits the notes' own paths first, and nothing else in the repo.
            paths = []
            if cfg["notes"].get("kind") != "mcp":
                folder, files = notes_files(cfg)
                paths = [x for x in folder + files
                         if os.path.exists(x) and (x == ws(repo) or x.startswith(ws(repo) + os.sep))]
            limit = int(cfg.get("push_timeout_s") or 180)
            try:
                r = subprocess.run([PUSH] + paths, capture_output=True, text=True, timeout=limit,
                                   env={**os.environ, "NOTES_REPO": ws(repo)})
                push = "ok" if r.returncode == 0 else "FAILED"
                if r.returncode:
                    notices.append(f"push.sh failed: {clean(r.stdout + r.stderr, 300)}")
            except (OSError, subprocess.TimeoutExpired) as e:  # the notes stay committed; the next push sends them
                push = "FAILED"
                notices.append(f"push.sh timed out after {limit}s" if isinstance(e, subprocess.TimeoutExpired)
                               else f"push.sh could not run: {clean(e, 300)}")
        cursor.update({"log_lines": upto, "since": now.isoformat(), "offsets": offsets})
        write_atomic(p("cursor.json"), json.dumps(cursor))
    if notices and not DRY:
        notice(notices, now)
    elif notices:  # a dry run changed nothing, so it tells the coordinator nothing; the person trying it sees them
        print("scribe: dry run, notices not written: " + "; ".join(clean(x, 200) for x in notices))
    health["fail_streak"] = 0
    write_atomic(p("health.json"), json.dumps(health))
    lines_part = f"{upto - done} ({done + 1}-{upto})" if upto > done else "0"
    append("runs.log", f"{stamp} | {'DRY | ' if DRY else ''}log lines: {lines_part} | inbox: {len(inbox)} | "
                       f"updated: {', '.join(updated) or '-'} | created: {', '.join(created) or '-'} | "
                       f"push: {push} | {time.time() - t0:.0f}s | {cost_part(res, cfg)} | {clean(out.get('summary'), 500)}")
    print(f"scribe {stamp}: {'DRY ' if DRY else ''}lines {lines_part}, inbox {len(inbox)}, updated {len(updated)}, "
          f"created {len(created)}, push {push}, {time.time() - t0:.0f}s, ${res.get('total_cost_usd', 0):.2f}, "
          f"tool calls {sum(calls.values())}")
    return 0


def main():
    global TZ
    os.makedirs(p("inbox", "done"), exist_ok=True)
    with open(p(".pass.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("scribe: another pass is still running, skipped")
            return 0
        try:
            cfg = load_config()
        except Exception as e:  # noqa: BLE001
            append("errors.log", f"{datetime.now():%Y-%m-%d %H:%M} | config | {clean(e, 400)}")
            print(f"scribe: config.json: {e}", file=sys.stderr)
            return 1
        TZ = ZoneInfo(cfg["timezone"]) if cfg.get("timezone") else None
        return run_pass(cfg)


def self_check():
    """Passes in a throwaway workspace with a stub claude and a throwaway notes repo. Touches nothing else."""
    global WORKSPACE, STATE, CONFIG, PROFILE, CLAUDE, DRY, PUSH
    tmp = tempfile.mkdtemp(prefix="scribe-check-")
    env = dict(os.environ)
    try:
        # A log rewritten smaller than the saved offset is read from its start; a growing one from the offset.
        rewritten = os.path.join(tmp, "rewritten.log")
        with open(rewritten, "w") as f:
            f.write("one\ntwo\n")
        assert tail_from(rewritten, 1000) == (["one", "two"], 8), tail_from(rewritten, 1000)
        assert tail_from(rewritten, 4) == (["two"], 8) and tail_from(rewritten, None) == ([], 8)

        # Plugins: the one whose server the notes or the tracker use stays on (off would stop its server).
        os.makedirs(os.path.join(tmp, "home", ".claude", "plugins"))
        with open(os.path.join(tmp, "home", ".claude", "plugins", "installed_plugins.json"), "w") as f:
            json.dump({"plugins": {"notes@market": [{}], "other@market": [{}]}}, f)
        os.environ["HOME"] = os.path.join(tmp, "home")
        assert plugin_switches({"notes": {"kind": "mcp", "server": "plugin_notes_vault"}}) == {
            "notes@market": True, "other@market": False}
        try:
            plugin_switches({"notes": {"kind": "mcp", "server": "plugin_gone_vault"}})
            raise AssertionError("notes served by a missing plugin were not refused")
        except ValueError as e:
            assert "plugin_gone_vault" in str(e), e

        os.environ.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        for who in ("AUTHOR", "COMMITTER"):
            os.environ[f"GIT_{who}_NAME"], os.environ[f"GIT_{who}_EMAIL"] = "check", "check@example.com"
        coord = os.path.join(tmp, "coordination")
        notes = os.path.join(coord, "notes")
        for d in ("bin", "coordination/permission-profiles", "coordination/tools/comms-watch/state", ".evidence/t1"):
            os.makedirs(os.path.join(tmp, d))
        WORKSPACE, STATE, CONFIG = tmp, os.path.join(tmp, "state"), os.path.join(tmp, "config.json")
        PROFILE, CLAUDE = os.path.join(coord, "permission-profiles", "watcher.json"), os.path.join(tmp, "bin", "claude")
        os.environ["STATE_DIR"] = STATE
        with open(PROFILE, "w") as f:
            json.dump({"permissions": {"deny": ["Bash(git push:*)"]}}, f)
        log = os.path.join(coord, "decision-log.md")
        with open(log, "w") as f:
            f.write("# Decision log\n- 2026-01-01 [C] old line (decided by: coordinator)\n")
        comms = os.path.join(coord, "tools", "comms-watch", "state", "log.md")
        open(comms, "w").close()
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", os.path.join(tmp, "origin.git")], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", notes], check=True)
        subprocess.run(["git", "-C", notes, "remote", "add", "origin", os.path.join(tmp, "origin.git")], check=True)
        subprocess.run(["git", "-C", notes, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
        subprocess.run(["git", "-C", notes, "push", "-q", "origin", "main"], check=True)
        cfg = {"timezone": "UTC", "decision_log": "coordination/decision-log.md", "evidence_dir": ".evidence",
               "notes": {"kind": "files", "dir": "coordination/notes", "handover": "coordination/handover.md",
                         "repo": "coordination/notes"},
               "context_logs": ["coordination/tools/comms-watch/state/log.md", "coordination/tools/none.log"]}
        with open(CONFIG, "w") as f:
            json.dump(cfg, f)
        # Stub claude: saves its arguments and the first message, writes one note (as an Edit would), and
        # returns every inbox note as handled. CHECK_DIE: exits at start without reading the first message.
        with open(CLAUDE, "w") as f:
            f.write("#!/usr/bin/env python3\nimport json, os, sys\n"
                    "if os.environ.get('CHECK_DIE'): sys.exit('stub: died at start')\n"
                    f"d, state, notes = {tmp!r}, {STATE!r}, {notes!r}\n"
                    "n = len([x for x in os.listdir(d) if x.startswith('args-')])\n"
                    "json.dump(sys.argv[1:], open(os.path.join(d, f'args-{n}.json'), 'w'))\n"
                    "open(os.path.join(d, f'prompt-{n}.txt'), 'w').write(sys.stdin.read())\n"
                    "open(os.path.join(notes, 'topic.md'), 'a').write(f'fact {n}\\n')\n"
                    "inbox = sorted(x for x in os.listdir(os.path.join(state, 'inbox')) if x.endswith('.md'))\n"
                    "print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'usage': {},\n"
                    "  'total_cost_usd': 0.2, 'num_turns': 2, 'structured_output': {\n"
                    "  'notes_updated': ['coordination/notes/topic.md'], 'notes_created': [],\n"
                    "  'inbox_handled': inbox, 'notices': ['created coordination/notes/topic.md'],\n"
                    "  'summary': 'one fact saved'}}))\n")
        os.chmod(CLAUDE, 0o755)

        def run():
            with contextlib.redirect_stdout(io.StringIO()):
                return main()

        def calls():
            return len([x for x in os.listdir(tmp) if x.startswith("args-")])

        # Run 1: no cursor yet, so it starts at the log's end: no news, no model.
        assert run() == 0 and calls() == 0
        assert open(p("runs.log")).read().splitlines()[-1].endswith("| no news")

        # Run 2: two new log lines, an inbox note, a changed evidence file, and a comms watcher line.
        with open(log, "a") as f:
            f.write("- 2026-01-02 [C] new line one (decided by: coordinator)\n- 2026-01-02 [B] new line two\n")
        with open(os.path.join(tmp, ".evidence", "t1", "walkthrough.md"), "w") as f:
            f.write("how it works\n")
        with open(comms, "a") as f:
            f.write("2026-01-02 10:00 | judgment | chat #team | Sam | asks for a date | link\n"
                    "2026-01-02 10:01 | noise | chat #random | bot | build bot | link\n")
        r = subprocess.run([os.path.join(HERE, "save.sh"), "the login bug was a stale token"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert run() == 0 and calls() == 1, open(p("runs.log")).read()
        prompt = open(os.path.join(tmp, "prompt-0.txt")).read()
        for want in ("3: - 2026-01-02 [C] new line one", "4: - 2026-01-02 [B] new line two", "stale token",
                     ".evidence/t1/walkthrough.md", "asks for a date"):
            assert want in prompt, (want, prompt)
        assert "build bot" not in prompt and "old line" not in prompt, prompt
        args = json.load(open(os.path.join(tmp, "args-0.json")))
        assert args[args.index("--tools") + 1] == "ToolSearch,Read,Grep,Glob,Edit,Write"
        allowed = args[args.index("--allowedTools") + 1].split(",")
        assert f"Edit(/{notes}/**)" in allowed and f"Write(/{coord}/handover.md)" in allowed, allowed
        assert not any(a.startswith("Edit(") and "decision-log" in a for a in allowed), allowed
        assert not [x for x in os.listdir(p("inbox")) if x.endswith(".md")] and len(os.listdir(p("inbox", "done"))) == 1
        assert len(os.listdir(p("notices"))) == 1
        pushed = subprocess.run(["git", "-C", os.path.join(tmp, "origin.git"), "log", "-1", "--format=%s", "main"],
                                capture_output=True, text=True).stdout.strip()
        assert pushed == "scribe: update notes", pushed
        assert "push: ok" in open(p("runs.log")).read().splitlines()[-1]
        assert json.load(open(p("cursor.json")))["log_lines"] == 4

        # Run 3: nothing new: no model.
        assert run() == 0 and calls() == 1

        # Runs 4 and 5: claude can't start (not there), then it exits at start, before it reads a first message
        # too big for the pipe. Both are failed passes: errors.log, runs.log, fail_streak; cursor and inbox kept.
        with open(log, "a") as f:
            f.write("- 2026-01-03 [C] start line\n")
        CLAUDE = os.path.join(tmp, "bin", "no-claude")
        assert run() == 1 and "FAILED (start)" in open(p("runs.log")).read().splitlines()[-1]
        CLAUDE = os.path.join(tmp, "bin", "claude")
        with open(log, "a") as f:
            f.write("- 2026-01-03 [B] a long line " + "x" * 300_000 + "\n")
        os.environ["CHECK_DIE"] = "1"
        assert run() == 1 and "died at start" in open(p("errors.log")).read().splitlines()[-1]
        del os.environ["CHECK_DIE"]
        assert json.load(open(p("cursor.json")))["log_lines"] == 4 and json.load(open(p("health.json")))[
            "fail_streak"] == 2

        # Run 6: push.sh hangs past push_timeout_s: the pass still ends, with a notice and the cursor moved on.
        with open(os.path.join(tmp, "bin", "push.sh"), "w") as f:
            f.write("#!/bin/sh\nexec sleep 30\n")
        os.chmod(os.path.join(tmp, "bin", "push.sh"), 0o755)
        PUSH = os.path.join(tmp, "bin", "push.sh")
        with open(CONFIG, "w") as f:
            json.dump({**cfg, "push_timeout_s": 1}, f)
        assert run() == 0 and calls() == 2, open(p("errors.log")).read()
        assert "push: FAILED" in open(p("runs.log")).read().splitlines()[-1]
        assert json.load(open(p("cursor.json")))["log_lines"] == 6
        assert any("push.sh timed out" in open(p("notices", x)).read() for x in os.listdir(p("notices")))
        PUSH = os.path.join(HERE, "push.sh")

        # Run 7: a dry run reads the new line but can't write; the cursor stays, and it writes no notices.
        with open(log, "a") as f:
            f.write("- 2026-01-03 [C] dry line\n")
        for x in os.listdir(p("notices")):
            os.remove(p("notices", x))
        DRY = True
        assert run() == 0 and calls() == 3
        args = json.load(open(os.path.join(tmp, "args-2.json")))
        assert args[args.index("--tools") + 1] == "ToolSearch,Read,Grep,Glob"
        assert not any(a.startswith(("Edit(", "Write(")) for a in args[args.index("--allowedTools") + 1].split(","))
        assert json.load(open(p("cursor.json")))["log_lines"] == 6
        assert "DRY RUN" in open(os.path.join(tmp, "prompt-2.txt")).read()
        assert not os.listdir(p("notices")), os.listdir(p("notices"))
    finally:
        DRY, PUSH = False, os.path.join(HERE, "push.sh")
        os.environ.clear()
        os.environ.update(env)
        shutil.rmtree(tmp, ignore_errors=True)
    print("self-check ok")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        self_check()
    elif "--interval" in sys.argv:
        print(int(float(load_config(strict=False).get("interval_min") or 20) * 60))
    else:
        sys.exit(main())
