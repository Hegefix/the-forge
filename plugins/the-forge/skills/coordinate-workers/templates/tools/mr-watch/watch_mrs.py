#!/usr/bin/env python3
"""mr-watch: polls your MRs and prints one line per change. A script, no model. start.sh runs it in tmux
session "mr-watch" and appends its output to events.log; the coordinator waits on that file with
wait_event.py.

It watches every open MR you authored, in every project, plus the MRs listed in mrs.txt next to this file
(one `group/project!iid` per line, `#` for comments; for MRs of others that you follow). The list is read
again on every pass, so there is nothing to restart. An MR that merges or closes is reported once, then
dropped.

A change line names the MR and what changed: state, draft, merge status, head pipeline (finished results
only), approvers, and a new comment by someone not in MR_WATCH_IGNORE.

GitLab only, through `glab api`.

Settings (environment):
  MR_WATCH_AUTHOR    your GitLab username (default: the user `glab` is logged in as)
  MR_WATCH_IGNORE    comma-separated usernames whose comments are not news (default: MR_WATCH_AUTHOR),
                     e.g. you plus your code-quality bot
  MR_WATCH_HOST      the GitLab host (default: glab's default host)
  MR_WATCH_INTERVAL  seconds between passes (default 90)
"""
import json, os, subprocess, sys, time, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIST = HERE / "mrs.txt"
HOST = os.environ.get("MR_WATCH_HOST")
INTERVAL = int(os.environ.get("MR_WATCH_INTERVAL", "90"))
QUIET_PIPELINE = ("running", "pending", "created", "waiting_for_resource", "preparing")


def api(path):
    args = ["glab", "api", *(["--hostname", HOST] if HOST else []), path]
    try:
        return json.loads(subprocess.check_output(args, stderr=subprocess.DEVNULL))
    except Exception:
        return None


def author():
    if os.environ.get("MR_WATCH_AUTHOR"):
        return os.environ["MR_WATCH_AUTHOR"]
    user = api("user")
    if not user:
        sys.exit("mr-watch: no GitLab user; log in with glab or set MR_WATCH_AUTHOR")
    return user["username"]


def listed():
    """MRs from mrs.txt: {"group/project!12": ("group%2Fproject", 12)}."""
    out = {}
    if LIST.exists():
        for line in LIST.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if "!" in line:
                project, iid = line.rsplit("!", 1)
                out[line] = (urllib.parse.quote(project, safe=""), int(iid))
    return out


def open_mrs(me):
    q = urllib.parse.urlencode({"author_username": me, "state": "opened", "scope": "all", "per_page": 100})
    mrs = api(f"merge_requests?{q}")
    if mrs is None:
        return None
    return {m["references"]["full"]: (str(m["project_id"]), m["iid"]) for m in mrs}


def main():
    me = author()
    ignore = set(filter(None, os.environ.get("MR_WATCH_IGNORE", me).split(",")))
    prev = {}
    while True:
        found = open_mrs(me)
        if found is not None:
            watch = {**found, **listed()}
            # An MR that left the open list gets one more pass, so its merge or close is reported.
            for key, (state, where) in prev.items():
                if key not in watch and state["state"] == "opened":
                    watch[key] = where
            for key, (proj, iid) in watch.items():
                p = f"projects/{proj}/merge_requests/{iid}"
                m, a, n = api(p), api(p + "/approvals"), api(p + "/notes?sort=desc&per_page=20")
                if not m or a is None or n is None:
                    continue
                notes = [x for x in n if not x["system"] and x["author"]["username"] not in ignore]
                state = {"state": m["state"], "draft": m["draft"], "status": m.get("detailed_merge_status"),
                         "pipe": (m.get("head_pipeline") or {}).get("status"),
                         "approved": sorted(x["user"]["username"] for x in a.get("approved_by", [])),
                         "last_note": notes[0]["id"] if notes else None}
                old = prev.get(key, (None, None))[0]
                if old and old != state:
                    ch = [f"{k}: {old[k]} -> {state[k]}" for k in state if old[k] != state[k] and k != "last_note"]
                    if old["last_note"] != state["last_note"] and notes:
                        ch.append(f"new note by {notes[0]['author']['username']}: {notes[0]['body'][:120]!r}")
                    if m["state"] == "merged" and old["state"] != "merged":
                        ch.append(f"target: {m['target_branch']}")
                    if ch and not (len(ch) == 1 and ch[0].startswith("pipe:") and state["pipe"] in QUIET_PIPELINE):
                        print(f"{key}: " + "; ".join(ch), flush=True)
                prev[key] = (state, (proj, iid))
            for key in [k for k in prev if k not in watch]:
                del prev[key]
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
