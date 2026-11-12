#!/usr/bin/env python3
# One board-watch pass: audits the tracker board against the git hosting's merge requests (read only).
#   python3 -I pass.py --scheduled   run a pass if a scheduled time has come and has not run yet (loop.sh calls this)
#   python3 -I pass.py --once        run one pass now
#   python3 -I pass.py --self-check  its tests, in a throwaway folder with a stub `claude` and `glab`
# By hand without touching the real state: STATE_DIR=state-test python3 -I pass.py --once
#
# The shell fetches the merge requests with `glab api` (GET only) and builds the first message. ONE headless
# `claude -p` with an empty context reads the tracker (read tools only, --permission-mode dontAsk) and returns a
# structured list of problems. The shell writes the digest: only items that were not in the previous pass.
import fcntl, json, os, re, shutil, signal, subprocess, sys, tempfile, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.environ.get("CLAUDE_BIN") or "claude"
GLAB = os.environ.get("GLAB_BIN") or "glab"
MAX_PAGES = 5   # 500 MRs per repo and state
KINDS = ["merged-not-in-test", "review-without-mr", "mr-open-ticket-not-started", "retest-needed",
         "release-scope", "missing-label", "overdue", "other"]
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items", "tracker"],
    "properties": {
        "items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["key", "kind", "now", "problem", "action"],
            "properties": {"key": {"type": "string"}, "kind": {"type": "string", "enum": KINDS},
                           "now": {"type": "string", "description": "the ticket's status now"},
                           "problem": {"type": "string"}, "action": {"type": "string"}}}},
        "tracker": {"type": "string", "description": "ok, or error: <what failed>"}}}


def load_config(path=None):
    with open(path or os.path.join(HERE, "config.json")) as f:
        c = json.load(f)
    if re.search(r"<[A-Za-z][^<>\"]*>", json.dumps(c)):
        raise ValueError("config.json still has a <placeholder>")
    return c


def clean(s, n=None):
    s = " ".join(str(s or "").replace("|", "/").split())
    return s if n is None or len(s) <= n else s[: n - 1] + "…"


class Pass:
    def __init__(self, cfg, state, workspace):
        self.cfg, self.state, self.ws = cfg, state, workspace
        self.tz = ZoneInfo(cfg.get("timezone") or "UTC")

    def p(self, *a):
        return os.path.join(self.state, *a)

    # ---- schedule -------------------------------------------------------------------------------------------
    def due_slot(self, now):
        """The latest scheduled time that has come (at most `grace_min` ago) and has not run yet, or None."""
        now = now.astimezone(self.tz)
        if now.isoweekday() not in self.cfg.get("days", [1, 2, 3, 4, 5]):
            return None
        grace = timedelta(minutes=self.cfg.get("grace_min", 180))
        slots = []
        for t in self.cfg["times"]:
            h, m = map(int, t.split(":"))
            slots.append(now.replace(hour=h, minute=m, second=0, microsecond=0))
        past = [s for s in slots if s <= now and now - s < grace]
        if not past:
            return None
        slot = max(past)
        done = self.load("slot.json", {})
        key = slot.strftime("%Y-%m-%dT%H:%M")
        if done.get("slot") == key:
            if done.get("ok") or done.get("tries", 0) >= 2:
                return None
            if now.timestamp() - done.get("at", 0) < self.cfg.get("retry_min", 20) * 60:
                return None   # a failed slot waits, so a short outage can clear before the second try
        return key

    # ---- small io -------------------------------------------------------------------------------------------
    def load(self, name, default):
        try:
            with open(self.p(name)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    def write(self, name, text):
        os.makedirs(os.path.dirname(self.p(name)), exist_ok=True)
        tmp = self.p(os.path.dirname(name), "." + os.path.basename(name) + ".tmp")
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, self.p(name))   # the waiter ignores dot files: it never sees a half-written digest

    def log(self, name, line):
        os.makedirs(self.state, exist_ok=True)
        with open(self.p(name), "a") as f:
            f.write(line.rstrip() + "\n")

    # ---- git hosting (GET only) -------------------------------------------------------------------------------
    def glab(self, path):
        r = subprocess.run([GLAB, "api", path], capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise RuntimeError(clean(r.stderr, 200) or f"glab exit {r.returncode}")
        return json.loads(r.stdout)

    def list_mrs(self, repo, state, extra):
        """Up to MAX_PAGES pages of 100 MRs; the second value says the list was cut."""
        enc = urllib.parse.quote(repo, safe="")
        out = []
        for page in range(1, MAX_PAGES + 1):
            batch = self.glab(f"projects/{enc}/merge_requests?state={state}&per_page=100&page={page}{extra}")
            out += batch
            if len(batch) < 100:
                return out, False
        return out, True

    def when(self, iso):
        """An API time (UTC, ends in Z) in the pass's zone, the zone the prompt and the tracker use."""
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(self.tz).strftime("%Y-%m-%d %H:%M")
        except (AttributeError, ValueError):
            return "-"

    def mr_lines(self, now):
        """One line per open MR and per MR merged in the last `merged_days` days, in every configured repo."""
        since = (now - timedelta(days=self.cfg.get("merged_days", 14))).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        jobs = [(repo, state, extra) for repo in self.cfg["repos"]
                for state, extra in (("opened", ""), ("merged", f"&updated_after={since}"))]

        def one(job):
            try:
                return job, self.list_mrs(*job), None
            except Exception as e:  # one repo failing must not stop the audit: the model is told
                return job, None, e
        with ThreadPoolExecutor(max_workers=min(8, len(jobs) or 1)) as ex:   # a hung host costs one timeout, not N
            results = list(ex.map(one, jobs))
        lines, failed, cut = [], [], []
        for (repo, state, _), got, err in results:
            if err:
                failed.append(f"{repo} ({state}): {clean(err, 100)}")
                continue
            batch, was_cut = got
            if was_cut:
                cut.append(f"{repo} ({state})")
            for m in batch:
                lines.append(" | ".join([
                    repo.split("/")[-1] + "!" + str(m["iid"]), m["state"] + (" draft" if m.get("draft") else ""),
                    "by " + ((m.get("author") or {}).get("username") or "?"),
                    "branch " + clean(m.get("source_branch"), 60), clean(m.get("title"), 90),
                    "merged " + self.when(m.get("merged_at")) if m["state"] == "merged"
                    else "updated " + self.when(m.get("updated_at")), m.get("web_url", "")]))
        return lines, failed, cut

    # ---- prompt ---------------------------------------------------------------------------------------------
    def user_text(self, now, mrs, failed, cut=()):
        c, t = self.cfg, self.cfg["tracker"]
        local = now.astimezone(self.tz)
        st = t["statuses"]
        out = [f"Board audit pass. Now: {local:%Y-%m-%d %H:%M} ({c.get('timezone') or 'UTC'}), {local:%A}.",
               f"Tracker: {t['server']} (tools: {', '.join(t['tools'])}). Project {t['project']}, label `{t['label']}`.",
               "Statuses: to do = " + ", ".join(st["todo"]) + "; in review = " + ", ".join(st["in_review"])
               + "; in test = " + ", ".join(st["test"]) + "; done = " + ", ".join(st["done"]) + ".",
               f"Board JQL: {t['board_jql']}",
               f"Overdue JQL: {t['overdue_jql']}"]
        if t.get("release_jql"):
            out.append(f"Release ({c.get('release', '')}) JQL: {t['release_jql']}")
        out.append(f"Tester: {c.get('tester') or 'none named'} (their last finding on a ticket = their last comment there).")
        out += ["", "Merge requests (git hosting, read by the shell; the ticket key is in the title or branch; "
                    f"times are {c.get('timezone') or 'UTC'}, like the time above):"]
        out += [f"- {x}" for x in mrs] or ["- (none)"]
        if failed:
            out += ["", "The shell could not read: " + "; ".join(failed) + ". Say nothing about MRs of those repos, "
                    "and skip checks 2 and 3 for this whole pass: a missing MR may be one the shell could not read."]
        if cut:
            out += ["", "These MR lists were cut at the first " + str(MAX_PAGES * 100) + ": " + "; ".join(cut)
                    + ". An MR missing from them may exist: do not report a ticket's MR as absent for these repos."]
        if c.get("hints"):
            out += ["", "Workspace rules:"] + [f"- {h}" for h in c["hints"]]
        return "\n".join(out)

    def allowed(self):
        t = self.cfg["tracker"]
        return ["mcp__" + t["server"] + "__" + x for x in t["tools"]]

    def settings(self):
        profile = os.path.join(self.ws, self.cfg["profile"])
        with open(profile) as f:
            s = json.load(f)   # a broken profile stops the pass here: fail closed, never run without it
        s.setdefault("permissions", {}).setdefault("deny", [])
        s["disableAllHooks"] = True
        s["claudeMdExcludes"] = ["**/CLAUDE.md", "**/CLAUDE.local.md", "**/AGENTS.md"]
        s["autoMemoryEnabled"] = False
        s["enabledPlugins"] = self.plugin_switches()
        path = self.p(".pass-settings.json")
        self.write(".pass-settings.json", json.dumps(s, indent=1))
        return path

    def plugin_names(self):
        names, home = set(), os.path.expanduser("~/.claude")
        for path, key in ((os.path.join(home, "plugins", "installed_plugins.json"), "plugins"),
                          (os.path.join(home, "settings.json"), "enabledPlugins")):
            try:
                with open(path) as f:
                    names |= set(json.load(f).get(key) or {})
            except Exception:
                pass
        return sorted(names)

    def plugin_switches(self):
        """Every plugin off, except the one whose MCP server the tracker names (plugin_<plugin>_<server>):
        a plugin switched off also stops its servers."""
        srv = self.cfg["tracker"]["server"]
        names = self.plugin_names()
        return {n: srv.startswith(f"plugin_{n.split('@')[0]}_") for n in names}

    def run_claude(self, settings, user_text, trace):
        c = self.cfg
        cmd = [CLAUDE, "-p", "--model", c.get("model", "sonnet"), "--settings", settings,
               "--permission-mode", "dontAsk", "--permission-prompts", "none",
               "--allowedTools", ",".join(self.allowed()), "--tools", "ToolSearch",
               "--disable-slash-commands", "--exclude-dynamic-system-prompt-sections",
               "--no-session-persistence", "--max-budget-usd", str(c.get("max_usd", 2)),
               "--json-schema", json.dumps(SCHEMA), "--append-system-prompt-file", os.path.join(HERE, "PASS.md"),
               "--output-format", "stream-json", "--verbose"]
        with open(trace, "w") as out, open(self.p(".pass-stderr.txt"), "w") as err:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=HERE, text=True,
                                    start_new_session=True)
            try:
                proc.communicate(user_text, timeout=c.get("timeout_s", 420))
                return proc.returncode
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(15)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                return "timeout"

    @staticmethod
    def read_result(trace):
        res = None
        with open(trace) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") == "result":
                    res = e
        return res or {}

    # ---- the pass -------------------------------------------------------------------------------------------
    def fp(self, i):
        return "|".join([clean(i["key"]), i["kind"], clean(i["now"])])

    def run(self, slot=None, now=None):
        os.makedirs(self.state, exist_ok=True)
        lock = open(self.p(".pass.lock"), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("board-watch: another pass is still running, skipped")
            return 0
        t0, now = time.time(), now or datetime.now(timezone.utc)
        stamp = now.astimezone(self.tz).strftime("%Y-%m-%d %H:%M")
        health = self.load("health.json", {"fail_streak": 0})
        sl = self.load("slot.json", {})

        def mark(ok):
            if slot:
                tries = sl.get("tries", 0) + 1 if sl.get("slot") == slot else 1
                self.write("slot.json", json.dumps({"slot": slot, "ok": ok, "tries": tries, "at": time.time()}))

        def fail(reason, detail):
            health["fail_streak"] = health.get("fail_streak", 0) + 1
            self.write("health.json", json.dumps(health))
            self.log("errors.log", f"{stamp} | {reason} | {clean(detail, 400)}")
            self.log("runs.log", f"{stamp} | FAILED {reason} | {time.time() - t0:.0f}s")
            if health["fail_streak"] == 3:
                self.digest(f"board-watch: 3 passes failed in a row ({reason}); see state/errors.log", now)
            mark(False)
            print(f"board-watch: FAILED {reason}")
            return 1

        try:
            settings = self.settings()
            mrs, failed, cut = self.mr_lines(now)
        except Exception as e:
            return fail("setup", e)
        if len(failed) == 2 * len(self.cfg["repos"]):
            return fail("git hosting", "; ".join(failed))
        trace = self.p("last-pass.jsonl")
        rc = self.run_claude(settings, self.user_text(now, mrs, failed, cut), trace)
        res = self.read_result(trace)
        out = res.get("structured_output")
        if rc != 0 or res.get("is_error") or not isinstance(out, dict):
            return fail(res.get("subtype") or f"exit {rc}", res.get("result") or open(self.p(".pass-stderr.txt")).read())
        if out["tracker"] != "ok":
            return fail("tracker", out["tracker"])
        try:   # a write after the paid run must not leave the slot undone: that would pay for another run
            health["fail_streak"] = 0
            self.write("health.json", json.dumps(health))
            items = out["items"]
            prev = set(self.load("last.json", {}).get("fps", []))
            new = [i for i in items if self.fp(i) not in prev]
            self.write("last.json", json.dumps({"at": stamp, "fps": sorted({self.fp(i) for i in items})}))
            self.write("open-items.md", "".join(f"{clean(i['key'])} | {clean(i['now'])} | {clean(i['problem'])} | {clean(i['action'])}\n" for i in items))
            name = None
            if new:
                body = f"board-watch: {len(new)} new ({len(items)} open), pass {stamp}\n" + "".join(
                    f"{clean(i['key'])} | {clean(i['now'])} | {clean(i['problem'], 200)} | {clean(i['action'], 200)}\n" for i in new)
                name = self.digest(body, now)
            cost = res.get("total_cost_usd", 0)
            self.log("runs.log", f"{stamp} | ok | {len(mrs)} MRs | {len(items)} items, {len(new)} new | digest {name or 'no'} "
                                 f"| {time.time() - t0:.0f}s | ${cost:.2f}")
            mark(True)
        except Exception as e:
            return fail("write", e)
        print(f"board-watch: {len(items)} items, {len(new)} new, digest {name or '-'}, ${cost:.2f}")
        return 0

    def digest(self, text, now):
        name = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".md"
        self.write(os.path.join("digests", name), text)
        return name


# ---- self-check ------------------------------------------------------------------------------------------------
def self_check():
    tmp = tempfile.mkdtemp(prefix="board-watch-check-")
    try:
        ws, state, bindir = (os.path.join(tmp, x) for x in ("ws", "state", "bin"))
        os.makedirs(os.path.join(ws, "prof")), os.makedirs(bindir)
        with open(os.path.join(ws, "prof", "watcher.json"), "w") as f:
            json.dump({"permissions": {"deny": ["Bash(x)"]}}, f)
        reply = os.path.join(tmp, "reply.json")
        with open(os.path.join(bindir, "claude"), "w") as f:
            f.write("#!/bin/sh\ncat >/dev/null\nprintf '%s\\n' \"$(cat '" + reply + "')\"\n")
        with open(os.path.join(bindir, "glab"), "w") as f:
            f.write("#!/bin/sh\ncase \"$*\" in *merged*) echo '[{\"iid\":7,\"state\":\"merged\",\"merged_at\":\"2026-01-02T10:00:00Z\","
                    "\"author\":{\"username\":\"a\"},\"source_branch\":\"k-1-x\",\"title\":\"K-1 x\",\"web_url\":\"u\"}]';; *) echo '[]';; esac\n")
        for x in ("claude", "glab"):
            os.chmod(os.path.join(bindir, x), 0o755)
        global CLAUDE, GLAB
        CLAUDE, GLAB = os.path.join(bindir, "claude"), os.path.join(bindir, "glab")
        cfg = {"timezone": "Europe/Amsterdam", "times": ["09:30", "15:30"], "profile": "prof/watcher.json",
               "repos": ["g/app"], "tracker": {"server": "t", "tools": ["search"], "project": "K", "label": "m",
               "statuses": {"todo": ["To Do"], "in_review": ["In Review"], "test": ["QA"], "done": ["Done"]},
               "board_jql": "j", "overdue_jql": "o"}}
        bw = Pass(cfg, state, ws)
        ams = ZoneInfo("Europe/Amsterdam")
        mon = datetime(2026, 11, 9, 9, 40, tzinfo=ams)
        assert bw.due_slot(mon) == "2026-11-09T09:30", "due after 09:30"
        assert bw.due_slot(datetime(2026, 11, 9, 9, 10, tzinfo=ams)) is None, "not due before 09:30"
        assert bw.due_slot(datetime(2026, 11, 9, 13, 0, tzinfo=ams)) is None, "09:30 slot older than grace"
        assert bw.due_slot(datetime(2026, 11, 8, 10, 0, tzinfo=ams)) is None, "Sunday"
        item = {"key": "K-1", "kind": "merged-not-in-test", "now": "In Review", "problem": "p | q", "action": "move"}

        def say(items, tracker="ok"):
            with open(reply, "w") as f:
                json.dump({"type": "result", "is_error": False, "total_cost_usd": 0.1,
                           "structured_output": {"items": items, "tracker": tracker}}, f)
        say([item])
        assert bw.run("2026-11-09T09:30", mon) == 0
        d = sorted(os.listdir(bw.p("digests")))
        assert len(d) == 1, "first pass writes a digest"
        text = open(bw.p("digests", d[0])).read()
        assert text.startswith("board-watch: 1 new") and "K-1 | In Review | p / q | move" in text, text
        assert bw.due_slot(mon) is None, "slot done"
        assert bw.run(None, mon + timedelta(hours=6)) == 0 and len(os.listdir(bw.p("digests"))) == 1, "same item: no digest"
        say([item, dict(item, key="K-2")])
        assert bw.run(None, mon + timedelta(hours=7)) == 0 and len(os.listdir(bw.p("digests"))) == 2, "new item: digest"
        say([], "error: down")
        assert bw.run(None, mon + timedelta(hours=8)) == 1, "tracker error fails the pass"
        assert os.path.exists(bw.p("errors.log"))
        # MR times are in the pass's zone (10:00Z is 11:00 in Amsterdam in January), and lists are told apart when cut
        lines, failed, cut = bw.mr_lines(mon)
        assert not failed and not cut and "merged 2026-01-02 11:00" in lines[0], lines
        assert "times are Europe/Amsterdam" in bw.user_text(mon, lines, [], [])
        txt = bw.user_text(mon, lines, ["g/app (opened): boom"], ["g/app (merged)"])
        assert "skip checks 2 and 3" in txt and "were cut at the first 500" in txt, txt
        # a repo with more than 100 MRs is read page by page, up to MAX_PAGES
        pages = []
        bw.glab = lambda path: pages.append(path) or [{"iid": len(pages)}] * 100
        got, was_cut = bw.list_mrs("g/app", "opened", "")
        assert was_cut and len(got) == 100 * MAX_PAGES and len(pages) == MAX_PAGES, (len(got), pages)
        del bw.glab
        # a plugin that serves the tracker's MCP server stays on, the others are off
        bw.plugin_names = lambda: ["tr@m", "other@m"]
        bw.cfg["tracker"]["server"] = "plugin_tr_jira"
        assert bw.plugin_switches() == {"tr@m": True, "other@m": False}, bw.plugin_switches()
        bw.cfg["tracker"]["server"] = "t"
        assert bw.plugin_switches() == {"tr@m": False, "other@m": False}
        del bw.plugin_names
        # a failed slot waits retry_min before its second try, and stops after two
        bw.write("slot.json", json.dumps({"slot": "2026-11-10T09:30", "ok": False, "tries": 1, "at": time.time()}))
        tue = datetime(2026, 11, 10, 9, 40, tzinfo=ams)
        bw.write("slot.json", json.dumps({"slot": "2026-11-10T09:30", "ok": False, "tries": 1, "at": tue.timestamp() - 60}))
        assert bw.due_slot(tue) is None, "retry too soon"
        bw.write("slot.json", json.dumps({"slot": "2026-11-10T09:30", "ok": False, "tries": 1, "at": tue.timestamp() - 25 * 60}))
        assert bw.due_slot(tue) == "2026-11-10T09:30", "retry after the wait"
        bw.write("slot.json", json.dumps({"slot": "2026-11-10T09:30", "ok": False, "tries": 2, "at": tue.timestamp() - 3600}))
        assert bw.due_slot(tue) is None, "two tries used"
        # a write that fails after the paid run marks the slot failed, never leaves it undone
        say([dict(item, key="K-9")])
        bw.write("slot.json", "{}")
        real_digest = bw.digest
        bw.digest = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
        assert bw.run("2026-11-10T09:30", tue) == 1
        assert json.load(open(bw.p("slot.json")))["ok"] is False and "write | disk full" in open(bw.p("errors.log")).read()
        bw.digest = real_digest
        # open-items.md keeps one row per item: a pipe or a newline in the model's text cannot split it
        say([dict(item, key="K-8", problem="a | b\nc")])
        assert bw.run(None, tue + timedelta(hours=1)) == 0
        assert open(bw.p("open-items.md")).read() == "K-8 | In Review | a / b c | move\n", open(bw.p("open-items.md")).read()
        print("self-check ok")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if "--self-check" in sys.argv:
        return self_check()
    cfg = load_config()
    ws = os.environ.get("WORKSPACE")
    if not ws:   # the first folder above this one that holds the permission profile
        d = HERE
        while d != os.path.dirname(d) and not os.path.exists(os.path.join(d, cfg["profile"])):
            d = os.path.dirname(d)
        ws = d
    state = os.path.abspath(os.environ.get("STATE_DIR") or os.path.join(HERE, "state"))
    bw = Pass(cfg, state, ws)
    if "--once" in sys.argv:
        return bw.run()
    if "--scheduled" in sys.argv:
        slot = bw.due_slot(datetime.now(timezone.utc))
        return bw.run(slot) if slot else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
