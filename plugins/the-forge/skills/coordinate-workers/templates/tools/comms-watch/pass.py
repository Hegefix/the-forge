#!/usr/bin/env python3
"""One comms watcher pass. loop.sh runs it on the schedule in config.json.

  python3 -I pass.py                one pass now (to try it on a copy of the state: STATE_DIR=state-test …)
  python3 -I pass.py --interval     seconds between passes right now, from config.json's schedule (0 = none)
  python3 -I pass.py --self-check   its tests: passes in a throwaway workspace with a stub claude and glab

1. Reads the cursor, pre-fetches the git hosting to-dos, and builds the prompt: PASS.md + the workspace's
   label rules as the system prompt file (the same text every pass, so it stays cached), and the window, the
   required chat steps, the sources and the decision-log tail as the first message.
2. Runs ONE headless `claude -p` with an empty context. Only the read tools listed in config.json can run
   (--permission-mode dontAsk + --allowedTools; nobody can answer a prompt). watcher.json's deny rules still
   apply, and without a valid profile no pass starts. No Bash, no file tools: the model reads and returns a
   structured result.
3. Writes what the model found: a digest file in state/digests/ (only when something isn't noise), log.md
   lines, a runs.log line and the cursor. A failed pass goes to errors.log and keeps the cursor.

Settings: config.json next to this file (see the helpers' README). Environment: WORKSPACE (default: three
folders up, the folder that holds coordination/), STATE_DIR (default: state/ here), CLAUDE_BIN (default:
claude on PATH), COMMS_WATCH_CONFIG (default: config.json here).
"""
import contextlib, fcntl, glob, io, json, math, os, re, shutil, signal, subprocess, sys, tempfile, time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.abspath(os.environ.get("WORKSPACE") or os.path.join(HERE, "..", "..", ".."))
STATE = os.path.abspath(os.environ.get("STATE_DIR") or os.path.join(HERE, "state"))
CONFIG = os.environ.get("COMMS_WATCH_CONFIG") or os.path.join(HERE, "config.json")
PROFILE = os.path.join(WORKSPACE, "coordination", "permission-profiles", "watcher.json")
CLAUDE = os.environ.get("CLAUDE_BIN") or "claude"
ALERT_AFTER = 3  # failures in a row before a digest says so
LABELS = ["human", "judgment", "mechanical", "fyi", "noise"]
PLACEHOLDER = re.compile(r"<[A-Za-z][^<>\"]*>")
TZ = None  # set from config.json; None = this machine's local time zone


def load_config(strict=True):
    with open(CONFIG) as f:
        text = f.read()
    cfg = json.loads(text)
    if strict and PLACEHOLDER.search(text):
        raise ValueError(f"{CONFIG} still has a placeholder: {PLACEHOLDER.search(text).group(0)}")
    return cfg


def p(name):
    return os.path.join(STATE, name)


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


def load_json(name, default):
    try:
        with open(p(name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def clean(s, n=None):
    s = " ".join(str(s or "").replace("|", "/").split())
    return s if n is None or len(s) <= n else s[: n - 1] + "…"


def servers(entry):
    """A source's MCP server name, or several names for one service (a claude.ai connector and a plugin)."""
    s = entry.get("server")
    return [s] if isinstance(s, str) else list(s or [])


def interval(cfg, now=None):
    """Seconds between passes at `now`: the first schedule window that matches, else otherwise_every_min."""
    now = now or datetime.now(timezone.utc).astimezone(TZ)
    dow, hm = now.isoweekday(), now.strftime("%H:%M")
    for w in cfg.get("schedule") or []:
        if dow in (w.get("days") or range(1, 8)) and w["from"] <= hm < w["to"]:
            return int(float(w["every_min"]) * 60)
    return int(float(cfg.get("otherwise_every_min") or 0) * 60)


def source_names(cfg):
    """The sources the model reports on, plus `git` (read by the shell)."""
    names = (["chat"] if cfg.get("chat") else []) + [s["name"] for s in cfg.get("sources") or []]
    return names, names + (["git"] if (cfg.get("git") or {}).get("todos") else [])


def schema(cfg):
    model_sources, _ = source_names(cfg)
    return {
        "type": "object", "additionalProperties": False,
        "required": ["items", "sources", "conversations_listed", "conversations_read", "threads_read"],
        "properties": {
            "items": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["time", "label", "urgent", "source", "who", "summary", "link", "suggested"],
                "properties": {
                    "time": {"type": "string", "description": "YYYY-MM-DD HH:MM, the first message's time zone"},
                    "label": {"type": "string", "enum": LABELS}, "urgent": {"type": "boolean"},
                    "source": {"type": "string"}, "who": {"type": "string"}, "summary": {"type": "string"},
                    "link": {"type": "string"}, "suggested": {"type": "string"}}}},
            "sources": {"type": "object", "additionalProperties": False, "required": model_sources,
                        "properties": {s: {"type": "string", "description": "ok, or error: <what failed>"}
                                       for s in model_sources}},
            "conversations_listed": {"type": "integer"},
            "conversations_read": {"type": "integer"},
            "threads_read": {"type": "integer"}}}


def allowed_tools(cfg):
    out = set()
    for entry in ([cfg["chat"]] if cfg.get("chat") else []) + list(cfg.get("sources") or []):
        out |= {f"mcp__{srv}__{t}" for srv in servers(entry) for t in entry.get("tools") or []}
    return sorted(out)


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
    """enabledPlugins for a pass: every plugin off, except the plugins whose MCP servers config.json names
    (plugin_<plugin>_<server>), because a plugin switched off also stops its servers. A source whose servers are
    all plugin servers that no installed plugin provides would never connect: ValueError with what to fix."""
    names = plugin_names()
    on = set()
    for entry in ([cfg["chat"]] if cfg.get("chat") else []) + list(cfg.get("sources") or []):
        srvs = servers(entry)
        found = {n for n in names for s in srvs if s.startswith(f"plugin_{n.split('@')[0]}_")}
        if srvs and not found and all(s.startswith("plugin_") for s in srvs):
            raise ValueError(f"config.json: {entry.get('name') or 'chat'} names only plugin servers "
                             f"({', '.join(srvs)}), and no installed plugin provides them: install the plugin, "
                             "or name the service's other server (a claude.ai connector) too")
        on |= found
    return {n: n in on for n in names}


def build_settings(cfg, plugins):
    with open(PROFILE) as f:
        s = json.load(f)  # a broken profile stops the pass here: fail closed, never run without it
    if PLACEHOLDER.search(json.dumps(s)):
        raise ValueError("watcher.json still has a <placeholder>")
    deny = s.setdefault("permissions", {}).setdefault("deny", [])
    deny += ["mcp__" + n for n in cfg.get("deny_servers") or []]  # tool names a pass never needs, out of context
    s["disableAllHooks"] = True
    s["claudeMdExcludes"] = ["**/CLAUDE.md", "**/CLAUDE.local.md", "**/AGENTS.md"]
    s["enabledPlugins"] = plugins
    s["autoMemoryEnabled"] = False
    path = p(".pass-settings.json")
    write_atomic(path, json.dumps(s, indent=1))
    return path


def system_prompt(cfg):
    """PASS.md + the workspace's label rules. The same text every pass, so the prompt cache holds it."""
    with open(os.path.join(HERE, "PASS.md")) as f:
        text = f.read()
    hints = [h for h in cfg.get("hints") or [] if h.strip()]
    text += "\n## This workspace's label rules\n\n" + ("\n".join(f"- {h}" for h in hints) or "- none") + "\n"
    path = p(".pass-system.md")
    write_atomic(path, text)
    return path


def git_items(cfg, since, until):
    """Git hosting to-dos for the human (GitLab, through glab). With the MR watch script running, the to-dos
    on the human's own MRs and on MRs they review are left out: MR watch reports those."""
    g = cfg.get("git") or {}
    user = g.get("username") or ""
    if not user:
        r = subprocess.run(["glab", "api", "user"], capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise RuntimeError(clean(r.stderr, 200) or f"glab exit {r.returncode}")
        user = json.loads(r.stdout)["username"]
    actions = {"mentioned", "directly_addressed", "assigned"}
    if not g.get("mr_watch_runs"):
        actions |= {"review_requested", "review_submitted", "build_failed", "unmergeable", "approval_required"}
    out = []
    for state in ("pending", "done"):
        for t in todos(state, since):
            created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
            if not since < created <= until or t["action_name"] not in actions:
                continue
            if (t.get("author") or {}).get("username") == user:
                continue
            tg = t.get("target") or {}
            if g.get("mr_watch_runs") and t["target_type"] == "MergeRequest" and (
                    (tg.get("author") or {}).get("username") == user
                    or user in [x.get("username") for x in tg.get("reviewers") or []]):
                continue
            ref = (tg.get("references") or {}).get("full") or t["project"]["path_with_namespace"]
            out.append(f"- {local(created)} | {t['action_name']} | {ref} {clean(tg.get('title'), 80)!r} | "
                       f"by {(t.get('author') or {}).get('username') or '?'} | to-do {t['state']} | "
                       f"{clean(t.get('body'), 300)!r} | {t['target_url']}")
    return out


def todos(state, since, per_page=100, max_pages=10):
    """The human's to-dos in `state`, page by page. GitLab lists them newest first, so the pages stop at the
    first one that reaches back to `since` (or isn't full). More than max_pages pages in a window fails git for
    this pass (it lags and is read again), so no to-do is dropped without a word."""
    out = []
    for page in range(1, max_pages + 1):
        r = subprocess.run(["glab", "api", f"todos?state={state}&per_page={per_page}&page={page}"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise RuntimeError(clean(r.stderr, 200) or f"glab exit {r.returncode}")
        batch = json.loads(r.stdout)
        out += batch
        if len(batch) < per_page or min(datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))
                                        for t in batch) <= since:
            return out
    raise RuntimeError(f"more than {max_pages * per_page} {state} to-dos since {local(since)}")


def run_claude(cfg, settings, system_file, user_text, trace):
    cmd = [CLAUDE, "-p", "--model", cfg.get("model") or "sonnet", "--settings", settings,
           "--permission-mode", "dontAsk", "--permission-prompts", "none",
           "--allowedTools", ",".join(allowed_tools(cfg)), "--tools", "ToolSearch",
           "--disable-slash-commands", "--exclude-dynamic-system-prompt-sections",
           "--no-session-persistence", "--max-budget-usd", str(cfg.get("max_usd") or 3),
           "--json-schema", json.dumps(schema(cfg)), "--append-system-prompt-file", system_file,
           "--output-format", "stream-json", "--verbose"]
    timeout = int(cfg.get("timeout_s") or 360)
    with open(trace, "w") as out, open(p(".pass-stderr.txt"), "w") as err:
        # Tool search stays on: ToolSearch waits for MCP servers that are still connecting. With it off, a
        # pass that starts before they connect has no tools at all.
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


# Slack: conversation ids, the ids in search results, and thread replies in search results' permalinks.
CONV_ID = re.compile(r"(?<![A-Z0-9])[CDG](?=[A-Z]*[0-9])[A-Z0-9]{8,12}(?![A-Z0-9])")
RESULT_CONV = re.compile(r"\(ID: ([CDG][A-Z0-9]{8,12})\)")
RESULT_THREAD = re.compile(r"archives/([CDG][A-Z0-9]{8,12})/p(\d{10})(\d{6})\?thread_ts=(\d+\.\d+)")


def result_text(content):
    """The plain text of a tool result (the Slack tools wrap theirs in a JSON string)."""
    out = []
    for c in content if isinstance(content, list) else [content]:
        t = c.get("text", "") if isinstance(c, dict) else str(c)
        try:
            v = json.loads(t)
            out += [x for x in (v.values() if isinstance(v, dict) else [v]) if isinstance(x, str)]
        except ValueError:
            out.append(t)
    return "\n".join(out)


def is_activity_search(inp):
    return inp.get("only_my_channels") in (True, "true") and "from:" not in str(inp.get("filters") or "")


def read_trace(trace):
    """The result event, the tool-call counts, and which Slack conversations were listed and read."""
    result, calls, list_ids, listed, read, searches = None, {}, set(), set(), set(), []
    act_ids, active, threads, threads_read = set(), set(), set(), set()
    with open(trace) as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            content = (e.get("message") or {}).get("content")
            if e.get("type") == "result":
                result = e
            elif e.get("type") == "assistant":
                for b in content or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        n, inp = b["name"].split("__")[-1], b.get("input") or {}
                        calls[n] = calls.get(n, 0) + 1
                        if n == "slack_list_user_channels":
                            list_ids.add(b.get("id"))
                        elif n == "slack_read_channel":
                            read.add(str(inp.get("channel_id")))
                        elif n == "slack_search_public_and_private":
                            searches.append(inp)
                            if is_activity_search(inp):
                                act_ids.add(b.get("id"))
                        elif n == "slack_read_thread":
                            threads_read.add(str(inp.get("message_ts")))
            elif e.get("type") == "user" and isinstance(content, list):
                for b in content:
                    if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                        continue
                    if b.get("tool_use_id") in list_ids:
                        listed |= set(CONV_ID.findall(json.dumps(b.get("content"))))
                    elif b.get("tool_use_id") in act_ids:
                        text = result_text(b.get("content"))
                        active |= set(RESULT_CONV.findall(text))
                        threads |= {(ch, th) for ch, sec, frac, th in RESULT_THREAD.findall(text)
                                    if th != f"{sec}.{frac}"}
    return result, calls, {"listed": listed, "read": read, "active": active, "threads": threads,
                           "threads_read": threads_read}, searches


def missing_searches(chat, searches):
    """The required Slack searches (steps 1, 4 and 5) that the trace doesn't show."""
    f = [str(x.get("filters") or "") for x in searches]
    need = {"activity search": any(is_activity_search(x) for x in searches),
            "replies to the human": any(f"from:<@{chat['user_id']}>" in y for y in f)}
    for w in chat.get("watch_people") or []:
        need[f"watch {w['name']}"] = any(f"from:<@{w['user_id']}>" in y for y in f)
    return [k for k, ok in need.items() if not ok]


def cost_part(res, cfg):
    if not res:
        return "cost ?"
    u = res.get("usage") or {}
    tin = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    return (f"${res.get('total_cost_usd', 0):.2f} | model {cfg.get('model') or 'sonnet'} | in {tin / 1000:.0f}k (cache read "
            f"{u.get('cache_read_input_tokens', 0) / 1000:.0f}k) out {u.get('output_tokens', 0) / 1000:.1f}k | "
            f"turns {res.get('num_turns', '?')}")


def digest_text(real, noise, notes):
    real = sorted(real, key=lambda i: (not (i["urgent"] and i["label"] == "human"), LABELS.index(i["label"]),
                                       i["time"]))
    counts = ", ".join(f"{label} {n}" for label in LABELS[:-1] if (n := sum(i["label"] == label for i in real)))
    head = f"comms-watch: {len(real)} new ({counts}" + (f"; {noise} noise logged" if noise else "") + ")"
    if any(i["urgent"] and i["label"] == "human" for i in real):
        head = "URGENT " + head
    lines = [head] + [f"[{i['label']}] {clean(i['source'])} — {clean(i['who'])} — {clean(i['summary'])} — "
                      f"{clean(i['link'])}" + (f" — suggested: {clean(i['suggested'])}" if clean(i["suggested"]) else "")
                      for i in real]
    return "\n".join(lines + notes) + "\n"


def link_key(link):
    """A stable key for one Slack message or Jira comment, whatever link form the model wrote; else None.
    A Slack ts is written three ways (p1793697825639569 in a permalink, 1793697825.639569, p1793697825.639569):
    the key keeps its digits only."""
    s = clean(link)
    m = re.search(r"archives/([CDG][A-Z0-9]{8,12})/p(\d{16})", s)
    if m:
        return f"slack:{m.group(1)}:{m.group(2)}"
    m = re.fullmatch(r"slack:([^:]+):p?(\d{10})\.?(\d{6})", s)
    if m:
        return f"slack:{m.group(1)}:{m.group(2)}{m.group(3)}"
    if s.startswith("slack:"):
        return s
    m = re.search(r"browse/([A-Z][A-Z0-9]*-\d+)\?.*focusedCommentId=(\d+)", s)
    if m:
        return f"jira:{m.group(1)}:{m.group(2)}"
    if s.startswith("jira:"):
        return s
    return None  # other links (a ticket, a page, an email) can stand for several events: no dedupe


def write_digest(text, now):
    os.makedirs(p("digests"), exist_ok=True)
    name = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".md"
    write_atomic(p(os.path.join("digests", name)), text)
    return name


def chat_lines(chat, win, until, full, sweep_from, carry, now):
    """The chat part of the first message: for Slack, the required steps with exact arguments."""
    key_ch, key_dm = chat.get("key_channels") or [], chat.get("key_dms") or []
    people = chat.get("watch_people") or []
    if chat.get("kind") != "slack":
        return [f"Chat ({', '.join(servers(chat))}): read every conversation with news since {local(win)}, threads "
                f"included; every pass also the key conversations {', '.join(key_ch + key_dm) or '-'}, the "
                f"replies to the human in threads, and the messages of {', '.join(w['name'] for w in people) or '-'}. "
                "No shell check for this chat server: be thorough."]
    oldest, latest = f"{win.timestamp():.6f}", f"{until.timestamp():.6f}"
    after, before = str(int(win.timestamp())), str(int(until.timestamp()))
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    three_days = (now.date() - timedelta(days=3)).isoformat()
    window = f'oldest="{oldest}", latest="{latest}"'
    lines = [f"This is a {'FULL SWEEP' if full else 'QUICK'} pass. Chat window: {window} (from {local(win)}). "
             "Required chat steps (exact arguments; the shell checks them in your trace):",
             f'1. slack_search_public_and_private(filters="after:{yesterday}", after="{after}", before="{before}", '
             'only_my_channels=true, sort="timestamp", include_context=false, limit=20), paged with cursor.',
             f'2. For each conversation in step 1: slack_read_channel(channel_id=<id>, {window}, limit=50). For each '
             f'thread reply in step 1: slack_read_thread(channel_id=<id>, message_ts=<its thread_ts>, {window}, '
             'response_format="concise").']
    key = []
    if key_ch:
        key.append(f'slack_read_channel(channel_id=<id>, limit=10) for {", ".join(key_ch)} (open threads with a '
                   'reply after since)')
    if key_dm:
        key.append(f'slack_read_channel(channel_id=<user id>, {window}) for {", ".join(key_dm)}')
    lines.append("3. " + ("; ".join(key) if key else "no key conversations") + ".")
    lines.append(f'4. slack_search_public_and_private(filters="from:<@{chat["user_id"]}> is:thread '
                 f'after:{three_days}", channel_types="public_channel,private_channel,mpim", sort="timestamp", '
                 'include_context=false, limit=20), paged with cursor; then slack_read_thread(channel_id=<id>, '
                 f'message_ts=<thread ts>, {window}, response_format="concise") for each distinct thread.')
    if people:
        lines.append("5. " + "; ".join(
            f'slack_search_public_and_private(filters="from:<@{w["user_id"]}> after:{yesterday}", after="{after}", '
            f'before="{before}", sort="timestamp", include_context=false, limit=20) ({w["name"]})'
            for w in people) + ".")
    if full:
        lines.append('6. FULL SWEEP: slack_list_user_channels(types="public_channel,private_channel,im,mpim", '
                     'exclude_archived=true, limit=200, format="ids_only"), then for EACH listed ID '
                     f'slack_read_channel(channel_id=<id>, oldest="{sweep_from.timestamp():.6f}", latest="{latest}", '
                     f'limit=50) (since the last sweep, {local(sweep_from)}).')
    if carry.get("channels") or carry.get("threads"):
        c_old = f"{datetime.fromisoformat(carry['from']).timestamp():.6f}"
        lines.append(f'7. Missed last pass, read now: slack_read_channel(channel_id=<id>, oldest="{c_old}", '
                     f'latest="{latest}", limit=50) for {", ".join(carry.get("channels") or []) or "-"}; '
                     f'slack_read_thread(channel_id=<id>, message_ts=<ts>, oldest="{c_old}", latest="{latest}", '
                     'response_format="concise") for '
                     f'{", ".join(f"{c} {t}" for c, t in carry.get("threads") or []) or "-"}.')
    return lines


def run_pass(cfg):
    t0 = time.time()
    now = datetime.now(timezone.utc).astimezone(TZ)
    until = now.replace(microsecond=0)
    chat = cfg.get("chat") or None
    slack = bool(chat) and chat.get("kind") == "slack"
    model_sources, all_sources = source_names(cfg)
    cursor = load_json("cursor.json", {"since": (until - timedelta(hours=2)).isoformat()})
    since = datetime.fromisoformat(cursor["since"])
    lagging = cursor.get("lagging") or {}
    src_since = {s: min(since, datetime.fromisoformat(lagging[s])) if s in lagging else since for s in all_sources}
    health = load_json("health.json", {"fail_streak": 0, "source_streak": {}})
    stamp = local(now)

    def fail(reason, detail, res=None):
        health["fail_streak"] = health.get("fail_streak", 0) + 1
        append("errors.log", f"{stamp} | {reason} | {clean(detail, 600)} | trace: failed-pass.jsonl")
        append("runs.log", f"{stamp} | FAILED ({reason}) | {time.time() - t0:.0f}s | {cost_part(res, cfg)} | cursor kept")
        if os.path.exists(p("last-pass.jsonl")):
            shutil.copyfile(p("last-pass.jsonl"), p("failed-pass.jsonl"))
        if health["fail_streak"] == ALERT_AFTER:
            write_digest(f"comms-watch: {ALERT_AFTER} passes failed in a row, nothing read since {local(since)} "
                         f"(last: {reason}: {clean(detail, 200)}). Look at {p('errors.log')}.\n", now)
        write_atomic(p("health.json"), json.dumps(health, indent=1))
        print(f"comms-watch {stamp}: pass FAILED ({reason})")
        return 1

    # Git hosting is read by the shell, not the model.
    gl, gl_error = [], None
    if "git" in all_sources:
        try:
            gl = git_items(cfg, src_since["git"], until)
        except Exception as e:  # noqa: BLE001 - any glab failure only lags git
            gl_error = f"error: {clean(e, 200)}"
    try:
        plugins = plugin_switches(cfg)
    except ValueError as e:
        return fail("config", str(e))
    try:
        settings = build_settings(cfg, plugins)
    except Exception as e:  # noqa: BLE001
        return fail("profile", f"{PROFILE}: {e}")
    system_file = system_prompt(cfg)
    try:
        with open(os.path.join(WORKSPACE, cfg.get("decision_log") or "coordination/decision-log.md")) as f:
            tail = "".join(f.readlines()[-30:])
    except OSError as e:
        tail = f"(decision log unreadable: {e})"

    def ts(dt):
        return f"{local(dt, '%Y-%m-%d %H:%M %Z')} = {dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"

    lines = [f"Run one comms-watch pass now ({local(now, '%A %Y-%m-%d %H:%M %Z')}).",
             f"The human: {cfg.get('human') or '-'}"
             + (f" (chat user id {chat['user_id']})" if chat and chat.get("user_id") else "") + ".",
             f"Window: since {ts(since)}, until {ts(until)}.",
             f"Sources to read and report in `sources`: {', '.join(model_sources) or 'none'}."]
    for s in model_sources:
        if src_since[s] < since:
            lines.append(f"{s} failed last pass: read it from {ts(src_since[s])}.")
    # QUICK pass: what the activity search shows changed, plus the key conversations. FULL SWEEP every
    # full_sweep_min (and after a failed chat read): also every conversation since the last sweep.
    last_full = datetime.fromisoformat(cursor["last_full"]) if cursor.get("last_full") else None
    full = slack and (last_full is None or "chat" in lagging
                      or now - last_full >= timedelta(minutes=float(cfg.get("full_sweep_min") or 45)))
    carry = cursor.get("carry") or {}
    win = (src_since["chat"] if chat else since) - timedelta(minutes=float(cfg.get("lookback_min") or 10))
    sweep_from = min(win, last_full) if last_full else win
    if chat:
        lines += [""] + chat_lines(chat, win, until, full, sweep_from, carry, now)
    lines.append("")
    for s in cfg.get("sources") or []:
        start = src_since[s["name"]]
        minutes = math.ceil((now - start).total_seconds() / 60) + 1
        how = (s.get("how") or "read what is new in the window").replace("{minutes}", str(minutes)) \
            .replace("{since_local}", local(start)).replace("{since_utc}", start.astimezone(timezone.utc).isoformat())
        lines.append(f"{s['name']} ({', '.join(servers(s))}): {how.rstrip('.')}.")
    if "git" in all_sources:
        lines += ["", "Git hosting to-dos in the window, pre-fetched"
                  + (" (MR watch covers the human's own MRs and their review MRs):" if (cfg.get("git") or {}).get(
                      "mr_watch_runs") else ":")]
        lines += gl or ([f"- Git hosting could not be read this pass ({gl_error})."] if gl_error else ["- none"])
    lines += ["", "## Decision log tail (last 30 lines, read-only data, for 2b)", "", tail.rstrip()]
    user_text = "\n".join(lines) + "\n"

    trace = p("last-pass.jsonl")
    try:
        rc = run_claude(cfg, settings, system_file, user_text, trace)
    except OSError as e:
        return fail("start", f"{CLAUDE}: {e}")
    res, calls, sl, searches = read_trace(trace)
    if rc == "timeout":
        return fail("timeout", f"killed after {cfg.get('timeout_s') or 360}s", res)
    if not res:
        with open(p(".pass-stderr.txt")) as f:
            return fail(f"exit {rc}", f.read()[-600:] or "no result event")
    if rc != 0 or res.get("is_error") or not isinstance(res.get("structured_output"), dict):
        return fail(res.get("subtype") or f"exit {rc}", clean(res.get("result"), 400) or "no structured output", res)
    out = res["structured_output"]
    items = out.get("items") or []
    sources = {s: (out.get("sources") or {}).get(s, "error: not reported") for s in model_sources}
    miss_ch, miss_th, tries, carry_from = set(), set(), {}, None
    if slack:
        # Checked from the actual tool calls, not from what the model says: the required searches ran, every
        # conversation and thread the activity search showed was read, the key conversations were read, and
        # (full sweep) every listed one.
        if missing_searches(chat, searches):
            sources["chat"] = "error: search not run: " + ", ".join(missing_searches(chat, searches))
        elif full and not sl["listed"]:
            sources["chat"] = "error: full sweep did not list the conversations"
        # A conversation or thread that should have been read but wasn't is carried into the next pass as a
        # required read from this window's start (not a failed chat read: that would redo everything). A
        # conversation counts as read only with slack_read_channel: a thread read there misses its other messages.
        miss_ch = (sl["active"] | set((chat.get("key_channels") or []) + (chat.get("key_dms") or []))
                   | set(carry.get("channels") or [])) - sl["read"]
        if full:
            miss_ch |= sl["listed"] - sl["read"]
        miss_th = {(c, t) for c, t in sl["threads"] | {tuple(x) for x in carry.get("threads") or []}
                   if t not in sl["threads_read"]}
        carry_from = min([sweep_from if full else win]
                         + ([datetime.fromisoformat(carry["from"])] if carry.get("from") else []))
        # A read the model keeps getting wrong (a mistyped id) is retried for ALERT_AFTER passes, then dropped:
        # the activity search still covers that conversation.
        tries = {k: (carry.get("tries") or {}).get(k, 0) + 1 for k in list(miss_ch) + [f"{c} {t}" for c, t in miss_th]}
        gave_up = sorted(k for k, n in tries.items() if n > ALERT_AFTER)
        if gave_up:
            append("errors.log", f"{stamp} | chat: gave up re-reading after {ALERT_AFTER} passes (search still "
                                 "covers): " + ", ".join(gave_up))
            miss_ch = {c for c in miss_ch if c not in gave_up}
            miss_th = {(c, t) for c, t in miss_th if f"{c} {t}" not in gave_up}
            tries = {k: n for k, n in tries.items() if k not in gave_up}
    if "git" in all_sources:
        sources["git"] = gl_error or "ok"
    failed = {s: v for s, v in sources.items() if not v.strip().lower().startswith("ok")}

    # Cursor: everything read up to `until`; a failed source keeps its old start for the next pass.
    new_cursor = {"since": until.isoformat()}
    if (miss_ch or miss_th) and "chat" not in failed:
        new_cursor["carry"] = {"from": carry_from.isoformat(), "channels": sorted(miss_ch),
                               "threads": sorted(miss_th), "tries": tries}
        append("errors.log", f"{stamp} | chat carry to next pass: {len(miss_ch)} conversations "
                             f"({', '.join(sorted(miss_ch)[:5])}), {len(miss_th)} threads")
    if full and "chat" not in failed:
        new_cursor["last_full"] = until.isoformat()
    elif last_full:
        new_cursor["last_full"] = last_full.isoformat()
    lag = {s: src_since[s].isoformat() for s in failed}
    if lag:
        new_cursor["lagging"] = lag
    notes, streak = [], health.setdefault("source_streak", {})
    for s in all_sources:
        streak[s] = streak.get(s, 0) + 1 if s in failed else 0
        if streak[s] == ALERT_AFTER:
            items.append({"time": stamp, "label": "mechanical", "urgent": False, "source": "comms-watch",
                          "who": "comms-watch", "link": p("errors.log"),
                          "summary": f"{s} unreadable for {ALERT_AFTER} passes since {local(src_since[s])}: "
                                     f"{clean(failed[s], 120)}",
                          "suggested": "check that connector's login"})
    if failed:
        notes.append("(not read this pass, re-read next pass: "
                     + "; ".join(f"{s} {clean(v, 80)}" for s, v in failed.items()) + ")")
        append("errors.log", f"{stamp} | sources | " + "; ".join(f"{s}: {clean(v, 200)}" for s, v in failed.items()))

    # The chat window overlaps the last pass (lookback_min) and a full sweep re-reads up to full_sweep_min: an
    # item already logged comes back. Drop it by its message key (Slack channel + ts, Jira comment id), kept
    # for 48 h in sent-links.json.
    sent = {}
    for k, v in load_json("sent-links.json", {}).items():
        if datetime.fromisoformat(v) > now - timedelta(hours=48):
            sent[link_key(k) or k] = v
    fresh, dups = [], 0
    for i in items:
        key = link_key(i["link"])
        if key and key in sent:
            dups += 1
            continue
        fresh.append(i)
        if key:
            sent[key] = now.isoformat()
    for i in fresh:
        append("log.md", f"{clean(i['time'])} | {i['label']} | {clean(i['source'])} | {clean(i['who'])} | "
                         f"{clean(i['summary'])} | {clean(i['link'])}")
    real = [i for i in fresh if i["label"] != "noise"]
    noise = len(fresh) - len(real)
    name = write_digest(digest_text(real, noise, notes), now) if real else None
    write_atomic(p("sent-links.json"), json.dumps(sent, indent=0))
    write_atomic(p("cursor.json"), json.dumps(new_cursor))
    health["fail_streak"] = 0
    write_atomic(p("health.json"), json.dumps(health, indent=1))
    chat_part = ""
    if slack:
        chat_part = (f" | chat {'FULL' if full else 'quick'}: "
                     f"changed {len(sl['active'] & sl['read'])}/{len(sl['active'])}"
                     + (f", swept {len(sl['listed'] & sl['read'])}/{len(sl['listed'])}" if full else "")
                     + f", read_channel {calls.get('slack_read_channel', 0)} thread {calls.get('slack_read_thread', 0)}"
                       f" search {calls.get('slack_search_public_and_private', 0)}"
                     + (f", carried {len(miss_ch)}+{len(miss_th)}" if miss_ch or miss_th else ""))
    append("runs.log", f"{stamp} | ok{' (partial: ' + ','.join(failed) + ')' if failed else ''} | items: {len(items)}"
                       f"{f' ({dups} seen before)' if dups else ''} | digest: {name or 'no (no news)'} | "
                       f"{time.time() - t0:.0f}s | {cost_part(res, cfg)}{chat_part}")
    print(f"comms-watch {stamp}: {len(real)} new, {noise} noise, {dups} seen before, digest {name or '-'}, "
          f"{time.time() - t0:.0f}s, ${res.get('total_cost_usd', 0):.2f}")
    return 0


def main():
    global TZ
    os.makedirs(STATE, exist_ok=True)
    with open(p(".pass.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("comms-watch: another pass is still running, skipped")
            return 0
        try:
            cfg = load_config()
        except Exception as e:  # noqa: BLE001
            append("errors.log", f"{datetime.now():%Y-%m-%d %H:%M} | config | {clean(e, 400)}")
            print(f"comms-watch: config.json: {e}", file=sys.stderr)
            return 1
        TZ = ZoneInfo(cfg["timezone"]) if cfg.get("timezone") else None
        return run_pass(cfg)


def self_check():
    """Passes in a throwaway workspace with a stub claude and a stub glab. Touches nothing else."""
    global WORKSPACE, STATE, CONFIG, PROFILE, CLAUDE, TZ
    tmp = tempfile.mkdtemp(prefix="comms-watch-check-")
    env = dict(os.environ)
    try:
        os.makedirs(os.path.join(tmp, "bin"))
        os.makedirs(os.path.join(tmp, "coordination", "permission-profiles"))
        # A throwaway ~/.claude with two plugins: "chat" serves the chat (plugin_chat_slack), "other" serves nothing.
        os.makedirs(os.path.join(tmp, "home", ".claude", "plugins"))
        with open(os.path.join(tmp, "home", ".claude", "plugins", "installed_plugins.json"), "w") as f:
            json.dump({"plugins": {"chat@market": [{}], "other@market": [{}]}}, f)
        os.environ["HOME"] = os.path.join(tmp, "home")
        WORKSPACE, STATE = tmp, os.path.join(tmp, "state")
        CONFIG, PROFILE = os.path.join(tmp, "config.json"), os.path.join(tmp, "coordination", "permission-profiles",
                                                                          "watcher.json")
        CLAUDE, TZ = os.path.join(tmp, "bin", "claude"), ZoneInfo("UTC")
        with open(PROFILE, "w") as f:
            json.dump({"permissions": {"deny": ["Bash(git push:*)"]}}, f)
        with open(os.path.join(tmp, "coordination", "decision-log.md"), "w") as f:
            f.write("- 2026-01-01 [C] an earlier decision (decided by: coordinator)\n")
        cfg = {"timezone": "UTC", "human": "Pat", "deny_servers": ["unused"],
               "schedule": [{"days": [1, 2, 3, 4, 5], "from": "08:00", "to": "19:00", "every_min": 20}],
               "otherwise_every_min": 120,
               "chat": {"kind": "slack", "server": ["connector_chat", "plugin_chat_slack"],
                        "tools": ["slack_read_channel", "slack_read_thread", "slack_search_public_and_private",
                                  "slack_list_user_channels"],
                        "user_id": "UHUMAN0001", "key_channels": ["CKEY000001"], "key_dms": ["UDM0000001"],
                        "watch_people": [{"name": "lead", "user_id": "ULEAD00001"}]},
               "sources": [{"name": "tracker", "server": "tracker_srv", "tools": ["search"],
                            "how": "search updated >= -{minutes}m"}],
               "git": {"todos": True, "username": "", "mr_watch_runs": True}, "hints": ["#random is noise"]}
        with open(CONFIG, "w") as f:
            json.dump(cfg, f)

        # Schedule: weekday daytime, weekday evening (otherwise), weekend.
        assert interval(cfg, datetime(2026, 1, 5, 9, 0, tzinfo=TZ)) == 1200
        assert interval(cfg, datetime(2026, 1, 5, 20, 0, tzinfo=TZ)) == 7200
        assert interval(cfg, datetime(2026, 1, 10, 9, 0, tzinfo=TZ)) == 7200

        # Slack message keys: a permalink and the ts forms the model writes are one message.
        assert (link_key("https://x.slack.com/archives/C0123ABCD/p1793697825639569?thread_ts=1793697000.000100")
                == link_key("slack:C0123ABCD:1793697825.639569") == link_key("slack:C0123ABCD:p1793697825639569")
                == "slack:C0123ABCD:1793697825639569")
        assert link_key("https://x.atlassian.net/browse/KEY-1?focusedCommentId=42") == "jira:KEY-1:42"

        # Plugins: the one whose server the config names stays on (off would stop its server), the rest off;
        # a source with only plugin servers that no installed plugin provides is refused with a clear message.
        assert plugin_switches(cfg) == {"chat@market": True, "other@market": False}, plugin_switches(cfg)
        try:
            plugin_switches({"chat": {"server": "plugin_gone_chat"}})
            raise AssertionError("a source served by a missing plugin was not refused")
        except ValueError as e:
            assert "plugin_gone_chat" in str(e), e

        # The plugin's watcher.json template denies the mail server's write tools one by one.
        tpl = os.path.join(HERE, "..", "..", "permission-profiles", "watcher.json")
        if os.path.exists(tpl) and "<mail-server>" in open(tpl).read():
            mail = [d.split("__")[-1] for d in json.load(open(tpl))["permissions"]["deny"]
                    if d.startswith("mcp__<mail-server>__")]
            for verb in ("send", "reply", "forward", "draft", "delete", "trash", "move", "label", "filter", "event",
                         "vacation"):
                assert any(verb in t for t in mail), (verb, mail)

        # Stub glab: the logged-in user, and two pages of pending to-dos (GitLab lists them newest first): 100
        # to-dos the pass skips, then a mention ten minutes ago and one by a deleted user (author null).
        def todo(minutes, action, author, ref, title):
            return {"created_at": (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"), "action_name": action, "author": author, "target_type": "Issue",
                    "target": {"title": title, "references": {"full": ref}},
                    "project": {"path_with_namespace": "group/app"}, "state": "pending", "body": "@me can you look",
                    "target_url": f"https://git.example.com/{ref.replace('#', '/-/issues/')}"}
        pages = [[todo(5, "marked", {"username": "sam"}, "group/app#1", "filler")] * 100,
                 [todo(10, "mentioned", {"username": "sam"}, "group/app#12", "Flaky login"),
                  todo(11, "mentioned", None, "group/app#13", "From a deleted user")]]
        with open(os.path.join(tmp, "todos.json"), "w") as f:
            json.dump(pages, f)
        glab = os.path.join(tmp, "bin", "glab")
        with open(glab, "w") as f:
            f.write("#!/usr/bin/env python3\nimport json, os, re, sys\n"
                    "a = sys.argv[-1]\n"
                    "page = int((re.search(r'[?&]page=(\\d+)', a) or [0, 1])[1])\n"
                    f"pages = json.load(open({os.path.join(tmp, 'todos.json')!r}))\n"
                    "if a == 'user': print(json.dumps({'username': 'me'}))\n"
                    "elif 'state=pending' in a: print(json.dumps(pages[page - 1] if page <= len(pages) else []))\n"
                    "else: print('[]')\n")
        os.chmod(glab, 0o755)
        os.environ["PATH"] = os.path.join(tmp, "bin") + os.pathsep + os.environ.get("PATH", "")

        # Stub claude: saves its arguments and the first message, then prints the trace in CHECK_TRACE (or fails;
        # CHECK_DIE: exits at start without reading the first message).
        with open(CLAUDE, "w") as f:
            f.write("#!/usr/bin/env python3\nimport json, os, sys\n"
                    "if os.environ.get('CHECK_DIE'): sys.exit('stub: died at start')\n"
                    f"d = {tmp!r}\n"
                    "n = len([x for x in os.listdir(d) if x.startswith('args-')])\n"
                    "json.dump(sys.argv[1:], open(os.path.join(d, f'args-{n}.json'), 'w'))\n"
                    "open(os.path.join(d, f'prompt-{n}.txt'), 'w').write(sys.stdin.read())\n"
                    "if os.environ.get('CHECK_FAIL'): sys.exit('stub: no result')\n"
                    "print(open(os.environ['CHECK_TRACE']).read())\n")
        os.chmod(CLAUDE, 0o755)
        link = "https://example.slack.com/archives/CACTIVE001/p1767600000000100"
        thread = "https://example.slack.com/archives/CACTIVE001/p1767600000000200?thread_ts=1767590000.000100"
        # CTHREAD01: the activity search shows it, but the pass reads only a thread there, not the conversation.
        other = "https://example.slack.com/archives/CTHREAD01/p1767600000000300?thread_ts=1767590000.000300"
        uses = [("s1", "slack_search_public_and_private", {"filters": "after:x", "only_my_channels": True}),
                ("s2", "slack_search_public_and_private", {"filters": "from:<@UHUMAN0001> is:thread"}),
                ("s3", "slack_search_public_and_private", {"filters": "from:<@ULEAD00001> after:x"}),
                ("l1", "slack_list_user_channels", {}),
                ("r1", "slack_read_channel", {"channel_id": "CACTIVE001"}),
                ("r2", "slack_read_channel", {"channel_id": "CKEY000001"}),
                ("r3", "slack_read_channel", {"channel_id": "UDM0000001"}),
                ("t1", "slack_read_thread", {"channel_id": "CTHREAD01", "message_ts": "1767590000.000300"})]
        trace = [{"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": i, "name": f"mcp__plugin_chat_slack__{n}", "input": inp}
                    for i, n, inp in uses]}},
                 {"type": "user", "message": {"content": [
                     {"type": "tool_result", "tool_use_id": "s1",
                      "content": [{"type": "text", "text": f"#team (ID: CACTIVE001) {link}\nreply {thread}\n"
                                                           f"#other (ID: CTHREAD01) top-level and reply {other}"}]},
                     {"type": "tool_result", "tool_use_id": "l1",
                      "content": [{"type": "text", "text": "CACTIVE001 CKEY000001 CSWEPT0001"}]}]}},
                 {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.3, "num_turns": 3,
                  "usage": {}, "structured_output": {
                      "items": [{"time": "2026-01-05 09:00", "label": "human", "urgent": False, "source": "chat #team",
                                 "who": "Sam", "summary": "asks Pat to pick the release date", "link": link,
                                 "suggested": "batch it"},
                                {"time": "2026-01-05 09:01", "label": "noise", "urgent": False, "source": "chat #random",
                                 "who": "bot", "summary": "build bot", "link": "", "suggested": ""}],
                      "sources": {"chat": "ok", "tracker": "ok"},
                      "conversations_listed": 3, "conversations_read": 3, "threads_read": 0}}]
        os.environ["CHECK_TRACE"] = os.path.join(tmp, "trace.jsonl")
        with open(os.environ["CHECK_TRACE"], "w") as f:
            f.write("\n".join(json.dumps(e) for e in trace) + "\n")

        def run():
            with contextlib.redirect_stdout(io.StringIO()):
                return main()

        # Pass 1: a full sweep; one item for the human, one noise; a thread reply and a swept channel unread.
        assert run() == 0, open(p("errors.log")).read() if os.path.exists(p("errors.log")) else "pass 1 failed"
        digests = sorted(os.listdir(p("digests")))
        assert len(digests) == 1, digests
        digest = open(p(os.path.join("digests", digests[0]))).read()
        assert digest.startswith("comms-watch: 1 new (human 1; 1 noise logged)") and "[human] chat #team" in digest, digest
        assert len(open(p("log.md")).read().splitlines()) == 2
        prompt = open(os.path.join(tmp, "prompt-0.txt")).read()
        for want in ("FULL SWEEP", "CKEY000001", "UDM0000001", 'from:<@ULEAD00001>', "tracker (tracker_srv): search "
                     "updated >= -", "group/app#12", "group/app#13", "by ?", "an earlier decision", "The human: Pat"):
            assert want in prompt, (want, prompt)
        assert "filler" not in prompt and "partial" not in open(p("runs.log")).read(), open(p("runs.log")).read()
        assert "| model sonnet | in " in open(p("runs.log")).read(), open(p("runs.log")).read()  # token-meter prices by it
        args = json.load(open(os.path.join(tmp, "args-0.json")))
        assert args[args.index("--permission-mode") + 1] == "dontAsk" and args[args.index("--tools") + 1] == "ToolSearch"
        allowed = args[args.index("--allowedTools") + 1].split(",")
        assert "mcp__connector_chat__slack_read_channel" in allowed, allowed
        assert "mcp__plugin_chat_slack__slack_read_thread" in allowed, allowed
        settings = json.load(open(args[args.index("--settings") + 1]))
        assert "mcp__unused" in settings["permissions"]["deny"] and "Bash(git push:*)" in settings["permissions"]["deny"]
        assert settings["disableAllHooks"] and settings["autoMemoryEnabled"] is False
        assert settings["enabledPlugins"] == {"chat@market": True, "other@market": False}, settings["enabledPlugins"]
        assert "#random is noise" in open(args[args.index("--append-system-prompt-file") + 1]).read()
        cursor = json.load(open(p("cursor.json")))
        assert cursor["carry"]["channels"] == ["CSWEPT0001", "CTHREAD01"], cursor
        assert cursor["carry"]["threads"] == [["CACTIVE001", "1767590000.000100"]], cursor
        assert "last_full" in cursor and "lagging" not in cursor, cursor

        # Pass 2: a quick pass that asks for the carried reads; the same item again is dropped, no digest.
        assert run() == 0
        assert len(os.listdir(p("digests"))) == 1, os.listdir(p("digests"))
        prompt = open(os.path.join(tmp, "prompt-1.txt")).read()
        assert "QUICK" in prompt and "Missed last pass" in prompt and "CSWEPT0001" in prompt, prompt
        assert "(1 seen before)" in open(p("runs.log")).read().splitlines()[-1]

        # Pass 3: claude fails; the cursor stays where it was.
        before = open(p("cursor.json")).read()
        os.environ["CHECK_FAIL"] = "1"
        assert run() == 1
        assert open(p("cursor.json")).read() == before and "FAILED" in open(p("runs.log")).read().splitlines()[-1]
        del os.environ["CHECK_FAIL"]

        # Pass 4: claude can't start (not there). Pass 5: it exits at start, before it reads a first message too
        # big for the pipe. Both are failed passes like any other; the third failure in a row writes a digest.
        CLAUDE = os.path.join(tmp, "bin", "no-claude")
        assert run() == 1, "pass 4"
        assert "FAILED (start)" in open(p("runs.log")).read().splitlines()[-1]
        CLAUDE = os.path.join(tmp, "bin", "claude")
        with open(os.path.join(tmp, "coordination", "decision-log.md"), "a") as f:
            f.write("- 2026-01-02 [B] a long line " + "x" * 300_000 + "\n")
        os.environ["CHECK_DIE"] = "1"
        assert run() == 1, "pass 5"
        assert "died at start" in open(p("errors.log")).read().splitlines()[-1], open(p("errors.log")).read()
        assert open(p("cursor.json")).read() == before and json.load(open(p("health.json")))["fail_streak"] == 3
        assert any("3 passes failed in a row" in open(p(os.path.join("digests", x))).read()
                   for x in os.listdir(p("digests"))), os.listdir(p("digests"))
    finally:
        os.environ.clear()
        os.environ.update(env)
        shutil.rmtree(tmp, ignore_errors=True)
    print("self-check ok")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        self_check()
    elif "--interval" in sys.argv:
        _cfg = load_config(strict=False)
        TZ = ZoneInfo(_cfg["timezone"]) if _cfg.get("timezone") else None
        print(interval(_cfg))
    else:
        sys.exit(main())
