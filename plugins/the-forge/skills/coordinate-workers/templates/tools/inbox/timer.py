"""Durable timers. The bridge loop (bridge.py) checks them every 30 s and posts an event when one fires.

  timer.py add --at "15:30" --text "stand-up notes"                  # once (HH:MM = next time it comes round)
  timer.py add --at "2030-01-07 09:00" --text "..."                  # once, exact local time
  timer.py add --every 2h [--at 10:00] [--until 18:00] --text "..."  # repeats; --at sets the first time
  timer.py add --when "mr_pipeline 123 45 success" --every 5m --tries 36 --text "!45 green" --priority high
  timer.py list [--all]          timer.py cancel <id> [<id> …]

--priority high|normal|low (default high: a timer is a wake-up you asked for). --link URL is copied into the event.
A `when` timer checks its condition every --every (default 5m), first on the next bridge pass (or at --at). It
fires once and ends when the condition holds, or ends after --tries checks (default 12) / at --until, and then
posts a "gave up" event at the same priority.

Conditions (a fixed list, no shell):
  http_ok <url>                          up = any answer but 5xx/429 (3xx and 4xx count as up); timeout = down
  mr_pipeline <project_id> <iid> <status>  the MR's head pipeline has this status (success, failed, …)
  mr_approved <project_id> <iid>         the MR has at least one approval
"""
import argparse, json, os, re, subprocess, sys, time, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

PIPELINE_STATUSES = {"created", "waiting_for_resource", "preparing", "pending", "running", "success", "failed",
                     "canceled", "skipped", "manual", "scheduled"}
KEEP_ENDED = 7 * 86400  # ended timers stay in timers.json this long (for `list --all`)


# ---- conditions --------------------------------------------------------------------------------------------

def parse_condition(s):
    """'mr_pipeline 123 45 success' -> ['mr_pipeline', '123', '45', 'success'], or ValueError."""
    t = s.split()
    name, args = (t[0], t[1:]) if t else ("", [])
    if name == "http_ok" and len(args) == 1 and re.match(r"https?://[^\s/]+", args[0]):
        return t
    if name == "mr_pipeline" and len(args) == 3 and args[0].isdigit() and args[1].isdigit() \
            and args[2] in PIPELINE_STATUSES:
        return t
    if name == "mr_approved" and len(args) == 2 and args[0].isdigit() and args[1].isdigit():
        return t
    raise ValueError(f"bad condition {s!r}; use one of: http_ok <http(s) url> | "
                     f"mr_pipeline <project_id> <iid> <{'|'.join(sorted(PIPELINE_STATUSES))}> | "
                     f"mr_approved <project_id> <iid>")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # a 3xx answer is an answer: the server is up


def http_ok(url, timeout=10):
    try:
        with urllib.request.build_opener(_NoRedirect).open(url, timeout=timeout) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
        e.close()
    except Exception as e:  # timeout, refused, DNS, TLS
        return False, f"down ({type(e).__name__})"
    return (code < 500 and code != 429), f"HTTP {code}"


def glab_api(path):
    out = subprocess.run(["glab", "api", path], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip()[:200])
    return json.loads(out.stdout)


def evaluate(cond):
    """-> (holds, detail). Errors count as 'not yet'."""
    name, args = cond[0], cond[1:]
    try:
        if name == "http_ok":
            return http_ok(args[0])
        mr = f"projects/{args[0]}/merge_requests/{args[1]}"
        if name == "mr_pipeline":
            status = (glab_api(mr).get("head_pipeline") or {}).get("status")
            return status == args[2], f"pipeline {status}"
        if name == "mr_approved":
            by = [a["user"]["username"] for a in glab_api(mr + "/approvals").get("approved_by", [])]
            return bool(by), f"approved by {', '.join(by)}" if by else "no approvals"
    except Exception as e:
        return False, f"error: {e}"
    return False, f"unknown condition {name}"


# ---- the timers file ---------------------------------------------------------------------------------------

def load():
    return common.read_json(common.TIMERS, {"next_id": 1, "timers": []})


def save(data):
    common.write_atomic(common.TIMERS, json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def _fire(t, n, text=None):
    # the creation time keeps ids unique when timers.json is reset and its ids start at 1 again
    return common.make_event("timer", t["kind"], t["priority"], text or t["text"], t["link"],
                             id=f"timer-{t['id']}-{int(t['created'])}-{n}")


def step(t, now, evaluate=evaluate):
    """One due timer -> (event or None, fields to update). Pure apart from `evaluate`."""
    kind, upd = t["kind"], {}
    if kind == "at":
        return _fire(t, 1), {"status": "done", "fired": 1, "ended": now}
    if kind == "every":
        if t.get("until") and t["next"] > t["until"]:
            return None, {"status": "done", "ended": now}
        nxt = t["next"] + t["interval"]
        while nxt <= now:  # missed runs (bridge was down) fire once, not many times
            nxt += t["interval"]
        upd = {"fired": t["fired"] + 1, "next": nxt}
        if t.get("until") and nxt > t["until"]:
            upd.update(status="done", ended=now)
        return _fire(t, t["fired"] + 1), upd
    holds, detail = evaluate(t["cond"])  # kind == "when"
    upd = {"checks": t["checks"] + 1, "last": detail}
    if holds:
        upd.update(status="done", fired=1, ended=now)
        return _fire(t, 1), upd
    if (t.get("tries") and upd["checks"] >= t["tries"]) or (t.get("until") and now >= t["until"]):
        upd.update(status="expired", ended=now)
        why = f"{upd['checks']} checks, last: {detail}"
        return _fire(t, "expired", f"timer {t['id']} gave up ({why}): {t['text']}"), upd
    upd["next"] = now + t["interval"]
    return None, upd


def run_due(now=None, post=common.post_events, evaluate=evaluate):
    """Called by the bridge each pass. Conditions are checked outside the lock, so `timer.py add` never waits
    on a slow URL. Then, under the lock, a timer cancelled meanwhile is dropped, and the events are posted
    before the timers are updated: after a crash the same event id comes back and the dedupe drops it."""
    now = now or time.time()
    with common.locked("timers"):
        due = [dict(t) for t in load()["timers"] if t["status"] == "active" and t["next"] <= now]
    if not due:
        return []
    results = [(t["id"],) + step(t, now, evaluate) for t in due]
    with common.locked("timers"):
        data = load()
        by_id = {t["id"]: t for t in data["timers"]}
        live = [(tid, e, upd) for tid, e, upd in results if tid in by_id and by_id[tid]["status"] == "active"]
        events = [e for _, e, _ in live if e]
        post(events)
        for tid, _, upd in live:
            by_id[tid].update(upd)
        save(data)
    return events


# ---- CLI ---------------------------------------------------------------------------------------------------

def fmt_dur(s):
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if s % n == 0:
            return f"{s // n}{unit}"
    return f"{s}s"


def describe(t, now=None):
    now = now or time.time()
    what = "once" if t["kind"] == "at" else f"every {fmt_dur(t['interval'])}"
    if t["kind"] == "when":
        what = f"when {' '.join(t['cond'])}, {what}"
        what += f", check {t['checks']}/{t['tries'] or '∞'}" + (f" ({t['last']})" if t.get("last") else "")
    if t.get("until"):
        what += f", until {common.fmt_local(t['until'], now)}"
    when = f"next {common.fmt_local(t['next'], now)}" if t["status"] == "active" else t["status"]
    return f"{t['id']:>3}  {when:<14} [{t['priority']}] {t['text']}  ({what})"


def add(a, now=None):
    now = now or time.time()
    kind = "when" if a.when else "every" if a.every else "at" if a.at else None
    if not kind:
        raise ValueError("give --at, --every or --when")
    if kind == "at" and (a.until or a.tries):
        raise ValueError("--until and --tries go with --every or --when")
    if kind == "every" and a.tries:
        raise ValueError("--tries goes with --when")
    if a.tries is not None and a.tries < 1:
        raise ValueError("--tries must be 1 or more")
    t = {"kind": kind, "status": "active", "text": a.text, "priority": a.priority, "link": a.link or "",
         "created": now, "interval": common.parse_duration(a.every or "5m") if kind != "at" else None,
         "until": common.parse_local(a.until, now, roll=False) if a.until else None,
         "cond": parse_condition(a.when) if a.when else None, "tries": None, "checks": 0, "fired": 0,
         "last": "", "ended": None}
    if kind == "when":
        t["tries"] = a.tries if a.tries else (None if a.until else 12)
    if a.at:
        t["next"] = common.parse_local(a.at, now)
    else:
        t["next"] = now if kind == "when" else now + t["interval"]
    if a.at and t["next"] <= now:
        raise ValueError(f"{a.at!r} is in the past")
    if t["until"] and t["until"] <= now:
        raise ValueError(f"--until {a.until!r} is in the past (HH:MM means today)")
    with common.locked("timers"):
        data = load()
        data["timers"] = [x for x in data["timers"] if x["status"] == "active" or (x["ended"] or now) > now - KEEP_ENDED]
        t = {"id": data["next_id"], **t}
        data["next_id"] += 1
        data["timers"].append(t)
        save(data)
    return t


def cancel(ids, now=None):
    out = []
    with common.locked("timers"):
        data = load()
        for t in data["timers"]:
            if t["id"] in ids and t["status"] == "active":
                t.update(status="cancelled", ended=now or time.time())
                out.append(t["id"])
        save(data)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add")
    pa.add_argument("--at"); pa.add_argument("--every"); pa.add_argument("--when"); pa.add_argument("--until")
    pa.add_argument("--tries", type=int)
    pa.add_argument("--text", required=True)
    pa.add_argument("--priority", choices=list(common.PRIORITIES), default="high")
    pa.add_argument("--link", default="")
    pl = sub.add_parser("list"); pl.add_argument("--all", action="store_true")
    pc = sub.add_parser("cancel"); pc.add_argument("ids", type=int, nargs="+")
    a = p.parse_args(argv)
    try:
        if a.cmd == "add":
            print("added " + describe(add(a)).strip())
        elif a.cmd == "list":
            ts = [t for t in load()["timers"] if a.all or t["status"] == "active"]
            print("\n".join(describe(t) for t in ts) or "no active timers")
        else:
            done = cancel(set(a.ids))
            print(f"cancelled {', '.join(map(str, done))}" if done else "nothing to cancel (unknown or not active)")
    except ValueError as e:
        sys.exit(f"timer.py: {e}")


if __name__ == "__main__":
    main()
