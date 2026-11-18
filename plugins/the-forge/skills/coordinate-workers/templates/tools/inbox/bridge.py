"""The inbox bridge: every 30 s it turns the other helpers' output into events and fires due timers.

  python3 -I bridge.py              # the loop (start.sh runs it in tmux `inbox`)
  python3 -I bridge.py --once       # one pass, then exit
  python3 -I bridge.py --check      # print the sources from config.json and whether each exists yet
  python3 -I bridge.py --backfill   # on first sight of a source, read it from the start (tests)

What it reads is in config.json next to it (or the file INBOX_CONFIG names); without that file, the defaults
below, which are the kit's own helpers. Paths start at COORD_ROOT (see common.py). It reads config.json once,
at start: restart the bridge after an edit.

It only reads the helpers' files; it never changes them. Its own read positions are in state/offsets.json and
are saved after the events are posted, so a crash re-reads at most one pass, and the dedupe on (source, id)
drops the repeats. On first sight of a source it starts at the current end (nothing old is replayed); a source
that doesn't exist yet is read from its start once it appears. Each pass writes state/heartbeat ("<epoch>
<pid>"); wait.py --status reads it.
"""
import argparse, json, os, re, sys, time, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common, timer

OFFSETS = os.path.join(common.STATE, "offsets.json")
CONFIG = os.environ.get("INBOX_CONFIG") or os.path.join(common.HERE, "config.json")
INTERVAL = 30

DEFAULT_CONFIG = {
    "sources": [
        {"name": "mr-watch", "log": "tools/mr-watch/events.log", "rule": "mr"},
        {"name": "janitor", "log": "tools/janitor/state/report.log", "rule": "janitor"},
        {"name": "load-check", "log": "tools/load-check/events.log", "rule": "load"},
        {"name": "token-meter", "log": "tools/token-meter/state/events.log", "rule": "tokens"},
        {"name": "comms-watch", "dir": "tools/comms-watch/state/digests", "rule": "digest"},
        {"name": "board-watch", "dir": "tools/board-watch/state/digests", "rule": "file", "priority": "high"},
        {"name": "scribe", "dir": "tools/scribe/state/notices", "rule": "file", "priority": "normal"},
    ],
    "mr": {"repos": [], "bots": [],
           "wake_on": ["-> merged", "-> closed", "-> failed", "approved: ", "conflict", "new note by "]},
    "digest": {"wake_on_labels": ["human", "judgment"]},
}

# ---- rules: one line or file -> (priority, text, link), or None to skip ------------------------------------

URL = re.compile(r"https?://\S+")
STAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d ")


def mr_rule(line, cfg):
    """mr-watch: '<group/project>!<iid>: <change>; <change>'. High when the MR's project is in mr.repos (an empty
    list means every MR) and the line has one of mr.wake_on, after the notes of mr.bots are cut off: a bot's
    note alone wakes nobody, but '-> merged; new note by <bot>: …' still does. Everything else is low."""
    project = line.split("!", 1)[0]
    repos = cfg["repos"]
    ours = not repos or any(project == r or project.endswith("/" + r) for r in repos)
    if ours and cfg["bots"]:
        line_cut = re.sub(r"new note by (%s):.*$" % "|".join(map(re.escape, cfg["bots"])), "", line)
    else:
        line_cut = line
    high = ours and any(w in line_cut for w in cfg["wake_on"])
    m = URL.search(line)
    return ("high" if high else "low"), line, (m.group(0) if m else "")


def janitor_rule(line, cfg):
    """KEEP / NO-MR lines wait for a decision -> normal. REMOVED, CLEANED, DRY … -> low."""
    text = STAMP.sub("", line)
    return ("normal" if text.startswith(("KEEP ", "NO-MR ")) else "low"), "janitor: " + text, ""


def load_rule(line, cfg):
    """'12:01 GREEN -> RED …' -> high when the new verdict is RED. Snapshot lines are skipped."""
    m = re.match(r"^\S+ (\S+) -> (\S+)", line)
    if not m:
        return None
    return ("high" if m.group(2) == "RED" else "low"), "load: " + line.split(" ", 1)[1], ""


def token_rule(line, cfg):
    """'2026-01-05 16:01 RED | today …' -> high when the verdict is RED."""
    text = STAMP.sub("", line)
    return ("high" if text.split(" ", 1)[0] == "RED" else "low"), "tokens: " + text, ""


def line_rule(line, cfg):
    return cfg.get("priority", "normal"), line, ""


def digest_rule(text, path, cfg):
    """comms-watch digests: high when a line starts with one of [<digest.wake_on_labels>] or the head says
    URGENT; else normal. The event text is the head plus those lines; the link is the file."""
    lines = [l for l in text.splitlines() if l.strip()]
    labels = "|".join(map(re.escape, cfg["wake_on_labels"]))
    items = [l for l in lines if labels and re.match(r"^\[(%s)\]" % labels, l)]
    head = lines[0] if lines else os.path.basename(path)
    high = items or head.startswith("URGENT")
    return ("high" if high else "normal"), " ⏎ ".join([head] + items), path


def file_rule(text, path, cfg):
    """Any file: the source's priority (default normal), its non-empty lines as the text."""
    return cfg.get("priority", "normal"), " ⏎ ".join(l for l in text.splitlines() if l.strip()), path


LOG_RULES = {"mr": mr_rule, "janitor": janitor_rule, "load": load_rule, "tokens": token_rule, "line": line_rule}
DIR_RULES = {"digest": digest_rule, "file": file_rule}


def load_config(path=None):
    """config.json (or the defaults) -> a checked config. Raises ValueError with what's wrong."""
    path = path or CONFIG
    try:
        with open(path) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        cfg = DEFAULT_CONFIG
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON: {e}")
    cfg = {"sources": cfg.get("sources", DEFAULT_CONFIG["sources"]),
           "mr": {**DEFAULT_CONFIG["mr"], **cfg.get("mr", {})},
           "digest": {**DEFAULT_CONFIG["digest"], **cfg.get("digest", {})}}
    names = set()
    for s in cfg["sources"]:
        name = s.get("name")
        if not name or name in names or name in ("timer", "hook"):
            raise ValueError(f"source {s}: needs a unique name (not timer or hook)")
        names.add(name)
        if ("log" in s) == ("dir" in s):
            raise ValueError(f"source {name}: give exactly one of log (a file read line by line) or dir")
        rules = LOG_RULES if "log" in s else DIR_RULES
        if s.get("rule") not in rules:
            raise ValueError(f"source {name}: rule must be one of {', '.join(rules)} for a {'log' if 'log' in s else 'dir'}")
        if s.get("priority", "normal") not in common.PRIORITIES:
            raise ValueError(f"source {name}: priority must be one of {', '.join(common.PRIORITIES)}")
    for key in ("repos", "bots", "wake_on"):
        if not isinstance(cfg["mr"][key], list):
            raise ValueError(f"mr.{key} must be a list")
    if not isinstance(cfg["digest"]["wake_on_labels"], list):
        raise ValueError("digest.wake_on_labels must be a list")
    return cfg


def rule_cfg(src, cfg):
    """What a rule sees: the source's own settings, plus mr/digest for those rules."""
    return {**cfg.get(src["rule"], {}), **src}


def where(src):
    return os.path.join(common.ROOT, src.get("log") or src["dir"])


# ---- readers -----------------------------------------------------------------------------------------------

def read_log(src, cfg, offsets, backfill):
    """New complete lines of an append-only log since the last read. offsets[name] keeps the byte position, the
    file's inode and a generation that goes up when the file is truncated or replaced, so a line that comes back
    at an old position after a rotation gets a new id instead of being dropped as a repeat."""
    name, path, rule = src["name"], where(src), LOG_RULES[src["rule"]]
    st = os.stat(path) if os.path.exists(path) else None
    size, ino = (st.st_size, st.st_ino) if st else (0, None)
    o = offsets.get(name)
    if not isinstance(o, dict):  # first sight: start at the end (a file that doesn't exist yet: at its start)
        o = {"pos": 0 if backfill or st is None else size, "ino": ino, "gen": 0}
    if size < o["pos"] or (o["ino"] is not None and ino is not None and ino != o["ino"]):
        o = {"pos": 0, "ino": ino, "gen": o["gen"] + 1}  # truncated or replaced: start over
    o["ino"] = ino if ino is not None else o["ino"]
    offsets[name] = o
    if size == o["pos"]:
        return []
    with open(path, "rb") as f:
        f.seek(o["pos"])
        data = f.read()
    events, pos, rc = [], o["pos"], rule_cfg(src, cfg)
    for raw in data.split(b"\n")[:-1]:  # the piece after the last newline is unfinished: next pass
        line = raw.decode("utf-8", "replace").rstrip("\r")
        r = rule(line, rc) if line.strip() else None
        if r:
            events.append(common.make_event(name, src.get("kind", src["rule"]), r[0], r[1], r[2],
                                            id=f"{o['gen']}:{common.line_id(pos, line)}"))
        pos += len(raw) + 1
    o["pos"] = pos
    return events


def read_dir(src, cfg, offsets, backfill):
    """New files (names that sort by time; dot files are skipped) since offsets[name], the last name read.
    One event per file; a file that can't be read becomes a normal event saying so, and the next files go on."""
    name, d, rule = src["name"], where(src), DIR_RULES[src["rule"]]
    files = sorted(f for f in os.listdir(d) if not f.startswith(".") and os.path.isfile(os.path.join(d, f))) \
        if os.path.isdir(d) else []
    if name not in offsets:
        offsets[name] = "" if backfill or not files else files[-1]
    events, rc = [], rule_cfg(src, cfg)
    for f in (f for f in files if f > offsets[name]):
        path = os.path.join(d, f)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                pri, text, link = rule(fh.read(), path, rc)
        except FileNotFoundError:
            continue
        except Exception as e:  # unreadable file or a rule bug: say so, don't block the files after it
            pri, text, link = "normal", f"{name}: could not read {f}: {type(e).__name__}: {e}", path
        events.append(common.make_event(name, src.get("kind", src["rule"]), pri, text, link, id=f))
        offsets[name] = f
    return events


def pass_once(cfg=None, backfill=False, now=None):
    cfg = cfg or load_config()
    offsets = common.read_json(OFFSETS, {})
    events = []
    for src in cfg["sources"]:
        try:
            events += (read_log if "log" in src else read_dir)(src, cfg, offsets, backfill)
        except Exception as e:  # one broken source must not stop the others
            log(f"{src['name']}: {type(e).__name__}: {e}")
    added = common.post_events(events)
    common.write_atomic(OFFSETS, json.dumps(offsets, indent=1, sort_keys=True) + "\n")
    added += timer.run_due(now)
    return added


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--once", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--backfill", action="store_true")
    a = p.parse_args()
    try:
        cfg = load_config()
    except ValueError as e:
        sys.exit(f"bridge.py: {e}")
    if a.check:
        print(f"config: {CONFIG if os.path.exists(CONFIG) else 'defaults (no ' + CONFIG + ')'}; paths from {common.ROOT}")
        for s in cfg["sources"]:
            print(f"  {s['name']:<12} {s['rule']:<8} {'found' if os.path.exists(where(s)) else 'not there yet'}  {where(s)}")
        return
    with common.locked("bridge", blocking=False) as ok:
        if not ok:
            sys.exit("bridge.py: another bridge is running (state/bridge.lock)")
        log(f"inbox bridge started, inbox {common.INBOX}, sources under {common.ROOT}")
        while True:
            try:
                added = pass_once(cfg, a.backfill)
                if added:
                    n = {k: sum(e["priority"] == k for e in added) for k in common.PRIORITIES}
                    log(f"posted {len(added)} (high {n['high']}, normal {n['normal']}, low {n['low']})")
                # only a pass that worked counts as alive: a bridge failing every pass looks down to wait.py
                common.write_atomic(common.HEARTBEAT, f"{time.time():.0f} {os.getpid()}\n")
            except Exception:
                log("pass failed:\n" + traceback.format_exc())
            if a.once:
                break
            time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
