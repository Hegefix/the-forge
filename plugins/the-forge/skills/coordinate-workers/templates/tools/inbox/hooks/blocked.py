"""Claude Code hook: tell the coordinator when a worker is blocked. Observes only: it never allows, denies or
changes anything, always exits 0 and prints nothing.

Reads the hook JSON on stdin and posts one HIGH inbox event (source "hook"):
  PermissionDenied                      auto mode blocked a tool call (tool_name, tool_input, tool_use_id, reason)
  Notification / permission_prompt      a worker has waited ~6 s on a permission dialog (message, title)
Any other shape is posted as a normal event with its JSON cut short. Field names: code.claude.com/docs/en/hooks.
The text names the worker (its .worktrees/<repo>/<task>, else its tmux session, else the cwd's folder), the
tool and a short, scrubbed summary of the input: no env values (KEY=…), nothing after password/token/secret,
no long token-like strings. Dedupe id: session_id + tool_use_id (or the second it fired).
The permission profiles register it (settings-snippet.json is the same block for any other settings file).
Errors go to <inbox>/state/hook-errors.log, never to the session.
"""
import json, os, re, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common

SUMMARY_KEYS = ("command", "file_path", "notebook_path", "path", "url", "pattern", "query", "description")
SECRET_WORD = re.compile(r"(?i)(password|passwd|token|secret|api[_-]?key|access[_-]?key|authorization|bearer|cookie).*",
                         re.S)
SCRUB = [
    (re.compile(r"\b([A-Z][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S+)"), r"\1=…"),     # env-style KEY=value
    (re.compile(r"://[^/\s:@]+:[^/\s@]+@"), "://…@"),                               # user:pass@ in URLs
    (re.compile(r"(^|\s)(-u|--user)([ =]?)[^\s:]+:\S+"), r"\1\2\3…"),             # curl -u user:pass
    (re.compile(r"\b(glpat-|gh[pousr]_|github_pat_|xox[abprs]-|sk-|AKIA)[A-Za-z0-9_\-]+"), r"\1…"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-.]+"), "…"),                                   # JWTs
    (re.compile(r"[A-Za-z0-9+_=]{32,}"), "…"),                                      # long token-like runs
]


def scrub(s, limit):
    s = " ".join(str(s).split())
    s = SECRET_WORD.sub(lambda m: m.group(1) + " …", s)
    for rx, rep in SCRUB:
        s = rx.sub(rep, s)
    return s if len(s) <= limit else s[:limit - 1] + "…"


def worker(cwd):
    m = re.search(r"/\.worktrees/([^/]+)/([^/]+)", cwd or "")
    if m:
        return f"{m.group(1)}--{m.group(2)}"
    if os.environ.get("TMUX"):
        try:
            args = ["tmux", "display-message", "-p"] + (["-t", os.environ["TMUX_PANE"]] if os.environ.get("TMUX_PANE") else []) + ["#S"]
            name = subprocess.run(args, capture_output=True, text=True, timeout=2).stdout.strip()
            if name:
                return name
        except Exception:
            pass
    return os.path.basename((cwd or "").rstrip("/")) or "?"


def summary(tool_input):
    if not isinstance(tool_input, dict):
        return scrub(tool_input, 120)
    for k in SUMMARY_KEYS:
        if isinstance(tool_input.get(k), str) and tool_input[k].strip():
            return scrub(tool_input[k], 120)
    return "keys: " + ", ".join(sorted(tool_input))[:120]


def event_for(d, now):
    who, sid, name = worker(d.get("cwd")), d.get("session_id", "?"), d.get("hook_event_name")
    eid = f"{sid}:{d.get('tool_use_id') or int(now)}"
    if name == "PermissionDenied":
        text = f"{who}: auto mode blocked {d.get('tool_name', '?')}: {summary(d.get('tool_input'))}"
        if d.get("reason"):
            text += f" — {scrub(d['reason'], 200)}"
        return common.make_event("hook", "permission-denied", "high", text, d.get("cwd", ""), id=eid)
    if name == "Notification" and d.get("notification_type") == "permission_prompt":
        text = f"{who}: waits on a permission dialog: {scrub(d.get('message') or d.get('title') or '', 200)}"
        return common.make_event("hook", "permission-prompt", "high", text, d.get("cwd", ""), id=eid)
    raw = {k: v for k, v in d.items() if k not in ("transcript_path", "scratchpad_dir")}
    return common.make_event("hook", "hook-other", "normal", f"{who}: hook {name}: {scrub(json.dumps(raw), 300)}",
                             d.get("cwd", ""), id=eid)


def main():
    now, raw = time.time(), ""
    try:
        raw = sys.stdin.read()
        try:
            d = json.loads(raw)
            ev = event_for(d if isinstance(d, dict) else {"hook_event_name": "?", "value": d}, now)
        except json.JSONDecodeError:
            ev = common.make_event("hook", "hook-other", "normal", f"hook: unreadable input: {scrub(raw, 300)}",
                                   id=f"raw:{int(now)}")
        common.post_events([ev])
    except Exception as e:
        try:
            os.makedirs(common.STATE, exist_ok=True)
            with open(os.path.join(common.STATE, "hook-errors.log"), "a") as f:
                f.write(f"{time.strftime('%F %T')} {type(e).__name__}: {scrub(e, 200)}\n")
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
