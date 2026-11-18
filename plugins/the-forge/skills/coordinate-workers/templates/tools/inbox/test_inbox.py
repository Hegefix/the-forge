"""Checks for the inbox, each in its own temp dir, no network. Run: python3 -I test_inbox.py  (about 15 s)."""
import http.server, importlib, json, os, shutil, subprocess, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common, timer, bridge  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="inbox-test-")
        self.env = dict(os.environ, INBOX_DIR=os.path.join(self.tmp, "inbox"), COORD_ROOT=os.path.join(self.tmp, "work"),
                        INBOX_POLL="0.2")
        os.environ.update({k: self.env[k] for k in ("INBOX_DIR", "COORD_ROOT")})
        for m in (common, timer, bridge):
            importlib.reload(m)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_py(self, script, *args, timeout=20, check=True):
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, script), *args], env=self.env,
                           capture_output=True, text=True, timeout=timeout)
        if check and r.returncode != 0:
            self.fail(f"{script} {args} exit {r.returncode}: {r.stdout}{r.stderr}")
        return r

    def post(self, text, priority="high", source="t", id=None):
        return common.post_events([common.make_event(source, "k", priority, text, id=id)])

    def events(self):
        return common.read_events()[0]


class Events(Base):
    def test_dedupe_on_source_and_id(self):
        self.assertEqual(len(self.post("a", id="1")), 1)
        self.assertEqual(self.post("a again", id="1"), [])
        self.assertEqual(len(self.post("other source", source="u", id="1")), 1)
        self.assertEqual(self.run_py("post.py", "--source", "t", "--id", "1", "--text", "x").stdout.strip(), "duplicate")
        self.assertEqual([e["seq"] for e in self.events()], [1, 2])

    def test_concurrent_writers(self):
        code = ("import sys; sys.path.insert(0, %r); import common\n"
                "for i in range(40): common.post_events([common.make_event('w', 'k', 'low', 'x', id=f'%%s-{i}' %% sys.argv[1]),"
                " common.make_event('w', 'k', 'low', 'shared', id=f'shared-{i}')])") % HERE
        procs = [subprocess.Popen([sys.executable, "-I", "-c", code, str(n)], env=self.env) for n in range(6)]
        for p in procs:
            self.assertEqual(p.wait(30), 0)
        evs = self.events()
        self.assertEqual(len(evs), 6 * 40 + 40)
        self.assertEqual([e["seq"] for e in evs], list(range(1, len(evs) + 1)))

    def test_half_written_line_is_left(self):
        self.post("one")
        with open(common.EVENTS, "a") as f:
            f.write('{"seq": 2, "id": "x"')
        evs, end = common.read_events()
        self.assertEqual(len(evs), 1)
        with open(common.EVENTS, "rb") as f:
            self.assertEqual(end, len(f.readline()))
        self.post("two")  # the cut line is closed off and skipped, the new event is intact
        self.assertEqual([(e["seq"], e["text"]) for e in self.events()], [(1, "one"), (2, "two")])
        with open(common.EVENTS, "a") as f:
            f.write('[]\n{}\n{"seq": "x", "source": "t", "id": "y"}\n"text"\n')  # valid JSON, not events
        self.post("three")
        self.assertEqual([(e["seq"], e["text"]) for e in self.events()], [(1, "one"), (2, "two"), (3, "three")])


class Wait(Base):
    def wait(self, *args, **kw):
        return self.run_py("wait.py", "--no-bridge-check", "--batch", "0.5", *args, **kw)

    def test_cursor_survives_and_nothing_is_lost_between_runs(self):
        self.post("A")
        self.assertIn("A", self.wait().stdout)
        self.post("B"); self.post("C")  # no waiter running
        out = self.wait().stdout
        self.assertIn("B", out); self.assertIn("C", out); self.assertNotIn(" A", out)
        p = subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "wait.py"), "--no-bridge-check", "--batch", "1"],
                             env=self.env, stdout=subprocess.PIPE, text=True)
        time.sleep(1); self.post("D"); time.sleep(0.3); self.post("E (in the batch window)")
        out, _ = p.communicate(timeout=10)
        self.assertIn("D", out); self.assertIn("E (in the batch", out)
        with open(os.path.join(common.STATE, "cursor")) as f:
            self.assertEqual(f.read().split()[0], "5")
        self.post("F")
        self.assertIn("F", self.run_py("wait.py", "--peek").stdout)
        self.assertIn("F", self.run_py("wait.py", "--peek").stdout)  # peek doesn't move the cursor

    def test_min_level_and_lower_events(self):
        self.post("just low", "low"); self.post("a normal one", "normal")
        r = subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "wait.py"), "--no-bridge-check", "--batch", "0.5"],
                             env=self.env, stdout=subprocess.PIPE, text=True)
        time.sleep(2)
        self.assertIsNone(r.poll())  # still blocked: nothing high
        self.post("the high one")
        out, _ = r.communicate(timeout=30)
        self.assertIn("the high one", out); self.assertIn("a normal one", out); self.assertNotIn("just low", out)
        self.assertIn("(+1 low not shown)", out)
        self.post("normal 2", "normal")
        self.assertIn("normal 2", self.wait("--min", "normal").stdout)

    def test_one_waiter_and_bridge_check(self):
        r = self.run_py("wait.py", check=False)
        self.assertEqual(r.returncode, 2); self.assertIn("bridge is not running", r.stdout)
        p = subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "wait.py"), "--no-bridge-check"], env=self.env)
        time.sleep(1)
        self.assertEqual(self.wait(check=False).returncode, 3)
        r = self.run_py("wait.py", "--status", check=False)
        self.assertEqual(r.returncode, 2); self.assertIn("waiter armed: yes", r.stdout); self.assertIn("NOT RUNNING", r.stdout)
        p.kill(); p.wait()
        self.assertIn("waiter armed: no", self.run_py("wait.py", "--status", check=False).stdout)


class Timers(Base):
    def add(self, *args):
        return self.run_py("timer.py", "add", *args).stdout

    def test_at_fires_once(self):
        self.add("--at", "2099-01-01 09:00", "--text", "far")
        self.assertEqual(timer.run_due(), [])
        due = common.parse_local("2099-01-01 09:00")
        self.assertEqual([e["text"] for e in timer.run_due(due + 1)], ["far"])
        self.assertEqual(timer.run_due(due + 999), [])
        self.assertEqual(timer.load()["timers"][0]["status"], "done")
        self.assertNotEqual(self.run_py("timer.py", "add", "--at", "2000-01-01 09:00", "--text", "x", check=False).returncode, 0)

    def test_every_until_and_missed_runs(self):
        t0 = time.time()
        self.add("--every", "10m", "--until", "2099-01-01 00:00", "--text", "tick", "--priority", "low")
        self.assertEqual(len(timer.run_due(t0 + 601)), 1)
        self.assertEqual(len(timer.run_due(t0 + 601 + 3600)), 1)  # six missed runs fire once
        t = timer.load()["timers"][0]
        self.assertEqual((t["fired"], t["status"]), (2, "active"))
        self.assertGreater(t["next"], t0 + 601 + 3600)
        self.assertEqual(len(timer.run_due(common.parse_local("2099-01-01 00:00") + 1)), 1)
        self.assertEqual(timer.load()["timers"][0]["status"], "done")

    def test_when_with_tries_and_cancel(self):
        self.add("--when", "mr_approved 1 2", "--every", "1m", "--tries", "2", "--text", "approved")
        no = lambda c: (False, "no approvals")
        self.assertEqual(timer.run_due(time.time() + 1, evaluate=no), [])
        gave_up = timer.run_due(time.time() + 61, evaluate=no)
        self.assertIn("gave up (2 checks, last: no approvals)", gave_up[0]["text"])
        self.add("--when", "mr_pipeline 1 2 success", "--text", "green")
        self.assertEqual(timer.run_due(time.time() + 1, evaluate=lambda c: (False, "pipeline running")), [])
        self.assertEqual([e["text"] for e in timer.run_due(time.time() + 301, evaluate=lambda c: (True, "ok"))], ["green"])
        self.add("--at", "2099-01-01 09:00", "--text", "cancel me")
        self.assertIn("cancelled 3", self.run_py("timer.py", "cancel", "3").stdout)
        self.assertEqual(timer.run_due(common.parse_local("2099-01-01 09:01")), [])
        for bad in ("rm -rf /", "http_ok file:///etc/passwd", "mr_pipeline 1 2 green", "mr_approved x 2"):
            self.assertNotEqual(self.run_py("timer.py", "add", "--when", bad, "--text", "x", check=False).returncode, 0)
        for bad in (["--when", "mr_approved 1 2", "--tries", "-3"], ["--every", "1h", "--at", "2000-01-01 09:00"]):
            self.assertNotEqual(self.run_py("timer.py", "add", *bad, "--text", "x", check=False).returncode, 0)

    def test_cancelled_while_checking_posts_nothing(self):
        self.add("--when", "mr_approved 1 2", "--text", "approved")

        def cancel_then_hold(cond):
            timer.cancel({1})  # someone cancels while the (slow) check runs
            return True, "approved by x"
        self.assertEqual(timer.run_due(time.time() + 1, evaluate=cancel_then_hold), [])
        self.assertEqual((self.events(), timer.load()["timers"][0]["status"]), ([], "cancelled"))

    def test_reset_timers_file_keeps_ids_unique(self):
        self.add("--at", "2099-01-01 09:00", "--text", "first")
        self.assertEqual(len(timer.run_due(common.parse_local("2099-01-01 09:00") + 1)), 1)
        os.remove(common.TIMERS)
        time.sleep(1.1)  # a new creation second
        self.add("--at", "2099-01-01 10:00", "--text", "second, also id 1")
        self.assertEqual(len(timer.run_due(common.parse_local("2099-01-01 10:00") + 1)), 1)
        self.assertEqual([e["text"] for e in self.events()], ["first", "second, also id 1"])

    def test_crash_between_post_and_save_is_deduped(self):
        self.add("--at", "2099-01-01 09:00", "--text", "once")
        due = common.parse_local("2099-01-01 09:00") + 1
        self.assertEqual(len(timer.run_due(due)), 1)
        data = timer.load(); data["timers"][0]["status"] = "active"; timer.save(data)  # as if the save was lost
        timer.run_due(due)  # fires again with the same event id
        self.assertEqual(len(self.events()), 1)

    def test_when_http_ok_against_local_server(self):
        codes = {"/ok": 200, "/redir": 302, "/missing": 404, "/busy": 429, "/bad": 503}

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(codes.get(self.path, 200)); self.send_header("Location", "/ok"); self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        srv.server_close()  # port known, server down
        url = f"http://127.0.0.1:{port}"
        self.add("--when", f"http_ok {url}/ok", "--every", "1s", "--tries", "5", "--text", "staging is up")
        self.run_py("bridge.py", "--once")
        self.assertEqual(self.events(), [])
        self.assertIn("down (URLError)", timer.load()["timers"][0]["last"])
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertEqual({p: timer.http_ok(url + p)[0] for p in codes},
                             {"/ok": True, "/redir": True, "/missing": True, "/busy": False, "/bad": False})
            time.sleep(1.1)
            self.run_py("bridge.py", "--once")
            self.assertEqual([e["text"] for e in self.events()], ["staging is up"])
        finally:
            srv.shutdown(); srv.server_close()
        self.assertFalse(timer.http_ok(url + "/ok")[0])


class Bridge(Base):
    MR = ["group/app!51: pipe: running -> failed",
          "group/app!51: approved: [] -> ['reviewer']",
          "group/app!51: new note by review-bot: 'LGTM; no conflict'",
          "group/app!51: state: opened -> merged; new note by review-bot: 'bye'",
          "group/app!51: pipe: running -> success",
          "group/other!7: state: opened -> merged",
          "group/sub/app!3: new note by pat: 'see https://git.example.com/x/-/merge_requests/3 please'"]

    def write(self, rel, text, mode="a"):
        path = os.path.join(self.tmp, "work", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f:
            f.write(text)

    def config(self, cfg):
        path = os.path.join(self.tmp, "config.json")
        with open(path, "w") as f:
            json.dump(cfg, f)
        return bridge.load_config(path)

    def test_rules(self):
        cfg = bridge.load_config()  # the kit's config.json: every MR counts, no bots
        rc = lambda rule: bridge.rule_cfg({"rule": rule}, cfg)
        self.assertEqual([bridge.mr_rule(l, rc("mr"))[0] for l in self.MR],
                         ["high", "high", "high", "high", "low", "high", "high"])
        cfg = self.config({"mr": {"repos": ["app"], "bots": ["review-bot"]}})
        self.assertEqual([bridge.mr_rule(l, rc("mr"))[0] for l in self.MR],
                         ["high", "high", "low", "high", "low", "low", "high"])
        self.assertEqual(bridge.mr_rule(self.MR[-1], rc("mr"))[2], "https://git.example.com/x/-/merge_requests/3")
        self.assertIsNone(bridge.load_rule("11:44 snapshot RED", {}))
        self.assertEqual(bridge.load_rule("17:58 YELLOW -> RED — load 2.00x", {})[0], "high")
        self.assertEqual(bridge.load_rule("18:01 RED -> YELLOW — load 0.89x", {})[0], "low")
        self.assertEqual(bridge.token_rule("2030-01-07 16:01 RED | today 91%", {})[0], "high")
        self.assertEqual(bridge.token_rule("2030-01-08 08:36 GREEN | today 0%", {})[0], "low")
        self.assertEqual(bridge.janitor_rule("2030-01-07 09:54 KEEP a: b", {})[0], "normal")
        self.assertEqual(bridge.janitor_rule("2030-01-07 09:54 NO-MR worktrees (left alone, decide): x", {})[0], "normal")
        self.assertEqual(bridge.janitor_rule("2030-01-07 09:54 DRY KEEP a", {})[0], "low")
        dg = rc("digest")
        self.assertEqual(bridge.digest_rule("comms-watch: 1 new (fyi 1)\n[fyi] x\n", "p", dg)[0], "normal")
        self.assertEqual(bridge.digest_rule("comms-watch: 1 new\n[judgment] reply to Pat\n", "p", dg),
                         ("high", "comms-watch: 1 new ⏎ [judgment] reply to Pat", "p"))
        self.assertEqual(bridge.digest_rule("URGENT comms-watch: 1 new\n[mechanical] x\n", "p", dg)[0], "high")
        dg = bridge.rule_cfg({"rule": "digest"}, self.config({"digest": {"wake_on_labels": ["fyi"]}}))
        self.assertEqual(bridge.digest_rule("comms-watch: 1 new\n[fyi] x\n", "p", dg)[0], "high")

    def test_config_is_checked(self):
        for bad in ({"sources": [{"name": "a", "log": "x", "dir": "y", "rule": "line"}]},
                    {"sources": [{"name": "a", "log": "x", "rule": "digest"}]},
                    {"sources": [{"name": "a", "log": "x", "rule": "line"}, {"name": "a", "dir": "y", "rule": "file"}]},
                    {"sources": [{"name": "timer", "log": "x", "rule": "line"}]},
                    {"sources": [{"name": "a", "dir": "y", "rule": "file", "priority": "urgent"}]},
                    {"mr": {"repos": "app"}}):
            with self.assertRaises(ValueError, msg=bad):
                self.config(bad)
        with open(os.path.join(self.tmp, "config.json"), "w") as f:
            f.write('{"sources": [ // no comments in JSON\n]}')
        self.assertIn("mr-watch", self.run_py("bridge.py", "--check").stdout)  # the kit's own config.json is fine
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "bridge.py"), "--once"], capture_output=True, text=True,
                           env=dict(self.env, INBOX_CONFIG=os.path.join(self.tmp, "config.json")), timeout=20)
        self.assertNotEqual(r.returncode, 0); self.assertIn("not valid JSON", r.stderr)

    def test_cr_lines_and_rotation(self):
        log = "tools/mr-watch/events.log"
        self.write(log, "")
        self.run_py("bridge.py", "--once")
        self.write(log, "group/app!1: progress 10%\r50%\rdone -> merged\n" + "group/app!2: -> failed\r\n")
        self.run_py("bridge.py", "--once")
        self.assertEqual([e["text"] for e in self.events()],
                         ["group/app!1: progress 10%\r50%\rdone -> merged", "group/app!2: -> failed"])
        self.write(log, "group/app!1: progress 10%\r50%\rdone -> merged\n", mode="w")  # truncated, same line again
        self.run_py("bridge.py", "--once")
        self.assertEqual(len(self.events()), 3)
        new = os.path.join(self.tmp, "work", log + ".new")
        with open(new, "w") as f:
            f.write("".join(f"group/app!{n}: -> closed\n" for n in range(10, 20)))  # replaced by a bigger file
        os.replace(new, os.path.join(self.tmp, "work", log))
        self.run_py("bridge.py", "--once")
        self.assertEqual([e["text"] for e in self.events()[3:]], [f"group/app!{n}: -> closed" for n in range(10, 20)])

    def test_bad_file_in_a_dir_source(self):
        for name in ("1.md", "2.md", "3.md"):
            self.write(f"notes/{name}", f"note {name}\n")
        src = {"name": "notes", "dir": "notes", "rule": "file"}
        real = bridge.DIR_RULES["file"]

        def rule(text, path, cfg):
            if path.endswith("2.md"):
                raise PermissionError("denied")
            return real(text, path, cfg)
        bridge.DIR_RULES["file"] = rule
        try:
            offsets = {}
            events = bridge.read_dir(src, bridge.load_config(), offsets, backfill=True)
        finally:
            bridge.DIR_RULES["file"] = real
        self.assertEqual([e["text"] for e in events],
                         ["note 1.md", "notes: could not read 2.md: PermissionError: denied", "note 3.md"])
        self.assertEqual(offsets["notes"], "3.md")

    def test_own_sources(self):
        self.config({"sources": [{"name": "deploys", "log": "logs/deploy.log", "rule": "line", "priority": "high"},
                                 {"name": "notes", "dir": "notes", "rule": "file"}]})
        env = dict(self.env, INBOX_CONFIG=os.path.join(self.tmp, "config.json"))
        once = lambda: subprocess.run([sys.executable, "-I", os.path.join(HERE, "bridge.py"), "--once"], env=env,
                                      capture_output=True, timeout=20, check=True)
        once()  # neither exists yet: both are read from the start once they appear
        self.write("logs/deploy.log", "prod deploy done\n")
        self.write("notes/20300107T100000Z.md", "a note\nline two\n")
        self.write("tools/mr-watch/events.log", self.MR[0] + "\n")  # not in this config: ignored
        once()
        self.assertEqual([(e["source"], e["priority"], e["text"]) for e in self.events()],
                         [("deploys", "high", "prod deploy done"), ("notes", "normal", "a note ⏎ line two")])

    def test_offsets_are_durable_and_incremental(self):
        self.write("tools/mr-watch/events.log", self.MR[0] + "\n")
        self.write("tools/comms-watch/state/digests/20300107T100000Z.md", "comms-watch: 1 new\n[fyi] old\n")
        self.run_py("bridge.py", "--once")
        self.assertEqual(self.events(), [])  # first sight starts at the end
        self.write("tools/mr-watch/events.log", self.MR[1] + "\n" + self.MR[4] + "\nhalf-written")
        self.write("tools/comms-watch/state/digests/20300107T110000Z.md", "comms-watch: 1 new\n[human] answer\n")
        self.write("tools/comms-watch/state/digests/.20300107T120000Z.md.tmp", "being written")
        self.write("tools/scribe/state/notices/20300107T110000Z.md", "scribe: a note\n")
        self.write("tools/load-check/events.log", "12:00 snapshot GREEN\n12:01 GREEN -> RED — swap\n")
        self.run_py("bridge.py", "--once")
        got = [(e["source"], e["priority"]) for e in self.events()]
        self.assertEqual(sorted(got), sorted([("mr-watch", "high"), ("mr-watch", "low"), ("comms-watch", "high"),
                                              ("scribe", "normal"), ("load-check", "high")]))
        self.write("tools/mr-watch/events.log", " line\n")
        self.run_py("bridge.py", "--once")
        self.assertEqual(self.events()[-1]["text"], "half-written line")
        self.run_py("bridge.py", "--once")
        self.assertEqual(len(self.events()), 6)  # nothing new, nothing repeated
        self.write("tools/mr-watch/events.log", self.MR[0] + "\n", mode="w")  # rotated
        self.run_py("bridge.py", "--once")
        self.assertEqual(self.events()[-1]["text"], self.MR[0])
        self.assertTrue(os.path.exists(common.HEARTBEAT))
        self.assertIn("bridge alive", self.run_py("wait.py", "--status").stdout)


class Hook(Base):
    def hook(self, payload):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        env = {k: v for k, v in self.env.items() if k not in ("TMUX", "TMUX_PANE")}
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "hooks", "blocked.py")], input=data, env=env,
                           capture_output=True, text=True, timeout=10)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))  # observe only: exit 0, say nothing
        return self.events()[-1] if self.events() else None

    def test_permission_denied_and_prompt(self):
        wt = "/home/me/ws/.worktrees/app/task-1/src"
        e = self.hook({"session_id": "s1", "cwd": wt, "hook_event_name": "PermissionDenied", "tool_name": "Bash",
                       "tool_input": {"command": "API_TOKEN=glpat-abcdefghij123456 curl -u bob:hunter2@x https://u:p@h/x "
                                      + "a" * 200, "description": "d"},
                       "tool_use_id": "toolu_1", "reason": "[Data Exfiltration]"})
        self.assertEqual((e["priority"], e["id"], e["kind"]), ("high", "s1:toolu_1", "permission-denied"))
        self.assertTrue(e["text"].startswith("app--task-1: auto mode blocked Bash: API_TOKEN"), e["text"])
        self.assertNotIn("glpat-abc", e["text"]); self.assertNotIn("hunter2", e["text"]); self.assertIn("[Data Exfiltration]", e["text"])
        e = self.hook({"session_id": "s1", "cwd": wt, "hook_event_name": "PermissionDenied", "tool_name": "Bash",
                       "tool_input": {"command": "DEBUG=1 export PW=x; mysql --password=abc"}, "tool_use_id": "toolu_2"})
        self.assertIn("DEBUG=… export PW=… mysql --password …", e["text"])
        e = self.hook({"session_id": "s1", "cwd": wt, "hook_event_name": "PermissionDenied", "tool_name": "Bash",
                       "tool_input": {"command": "curl -u bob:hunter2 https://h/x?access_key=k1"}, "tool_use_id": "toolu_4"})
        self.assertIn("curl -u … https://h/x?access_key …", e["text"]); self.assertNotIn("hunter2", e["text"])
        e = self.hook({"session_id": "s2", "cwd": "/tmp/somewhere", "hook_event_name": "PermissionDenied",
                       "tool_name": "Write", "tool_input": {"file_path": "/tmp/somewhere/a.txt", "content": "S3CRET"},
                       "tool_use_id": "toolu_3"})
        self.assertIn("somewhere: auto mode blocked Write: /tmp/somewhere/a.txt", e["text"]); self.assertNotIn("S3CRET", e["text"])
        e = self.hook({"session_id": "s3", "cwd": wt, "hook_event_name": "Notification", "notification_type": "permission_prompt",
                       "message": "Claude needs your permission to use Bash", "title": "Permission needed"})
        self.assertEqual((e["priority"], e["kind"]), ("high", "permission-prompt"))
        self.assertIn("waits on a permission dialog: Claude needs your permission to use Bash", e["text"])
        self.hook({"session_id": "s1", "cwd": wt, "hook_event_name": "PermissionDenied", "tool_name": "Bash",
                   "tool_input": {"command": "x"}, "tool_use_id": "toolu_1"})
        self.assertEqual(len(self.events()), 5)  # same session + tool_use_id: deduped

    def test_other_shapes(self):
        e = self.hook({"session_id": "s", "cwd": "/a/b", "hook_event_name": "Notification", "notification_type": "idle_prompt",
                       "message": "waiting " + "x" * 500})
        self.assertEqual((e["priority"], e["kind"]), ("normal", "hook-other")); self.assertLessEqual(len(e["text"]), 330)
        e = self.hook("not json at all")
        self.assertIn("unreadable input", e["text"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
