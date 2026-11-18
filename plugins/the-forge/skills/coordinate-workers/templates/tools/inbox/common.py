"""Shared parts of the inbox: paths, locks, the event log (events.jsonl) and time helpers.

Run every script here with `python3 -I`. That keeps the script's folder off sys.path, so each script adds its
own folder before `import common`.

Paths: INBOX_DIR (default: this folder) holds events.jsonl, timers.json and state/. COORD_ROOT (default: two
folders up, the workspace's `coordination/` folder) is where the paths in config.json start. Tests set both.
"""
import contextlib, fcntl, hashlib, json, os, re, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.abspath(os.environ.get("INBOX_DIR") or HERE)
ROOT = os.path.abspath(os.environ.get("COORD_ROOT") or os.path.join(HERE, "..", ".."))
STATE = os.path.join(INBOX, "state")
EVENTS = os.path.join(INBOX, "events.jsonl")
TIMERS = os.path.join(INBOX, "timers.json")
HEARTBEAT = os.path.join(STATE, "heartbeat")

PRIORITIES = {"low": 0, "normal": 1, "high": 2}
FIELDS = ("id", "ts", "source", "kind", "priority", "text", "link")


# ---- files and locks ---------------------------------------------------------------------------------------

@contextlib.contextmanager
def locked(name, blocking=True):
    """Exclusive fcntl lock on state/<name>.lock. With blocking=False, yields False when someone else holds it."""
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, name + ".lock"), "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            f.seek(0); f.truncate(); f.write(f"{os.getpid()}\n"); f.flush()
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


# ---- events ------------------------------------------------------------------------------------------------

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def line_id(offset, line):
    """Stable id for a line of an append-only log: where it starts plus a short hash (lines can repeat)."""
    return f"{offset}:{hashlib.sha1(line.encode()).hexdigest()[:10]}"


def make_event(source, kind, priority, text, link="", id=None, ts=None):
    if priority not in PRIORITIES:
        raise ValueError(f"priority must be one of {', '.join(PRIORITIES)}: {priority!r}")
    ts = ts or now_iso()
    id = id or hashlib.sha1(f"{ts} {text} {time.time_ns()}".encode()).hexdigest()[:12]
    return {"id": str(id), "ts": ts, "source": source, "kind": kind, "priority": priority,
            "text": text, "link": link or ""}


def read_events(offset=0):
    """Complete events from byte `offset` on, as (events, new_offset). A half-written last line is left for
    the next read (writers hold a lock, readers don't)."""
    try:
        with open(EVENTS, "rb") as f:
            f.seek(offset)
            data = f.read()
    except FileNotFoundError:
        return [], 0
    end = data.rfind(b"\n") + 1
    events = []
    for l in data[:end].split(b"\n"):
        try:
            e = json.loads(l)
        except ValueError:  # a line cut by a crash: skip it rather than stop every reader
            continue
        if isinstance(e, dict) and isinstance(e.get("seq"), int) and "source" in e and "id" in e:
            events.append(e)  # anything else in the file is not an event: skip it too
    return events, offset + end


def post_events(events):
    """Append events, skipping any whose (source, id) is already in the log. Assigns `seq` (1, 2, 3 …, never
    reused). Safe with concurrent writers: everything happens under one lock. Returns the events added."""
    if not events:
        return []
    with locked("events"):
        seen, seq = set(), 0
        for e in read_events()[0]:
            seen.add((e["source"], e["id"]))
            seq = max(seq, e.get("seq", 0))
        added = []
        for e in events:
            key = (e["source"], str(e["id"]))
            if key in seen:
                continue
            seen.add(key)
            seq += 1
            added.append({"seq": seq, **{k: e.get(k, "") for k in FIELDS}})
        if added:
            os.makedirs(INBOX, exist_ok=True)
            with open(EVENTS, "a+b") as f:
                if f.tell():
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        f.write(b"\n")  # never glue an event onto a line a crash left unfinished
                f.write("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in added).encode())
                f.flush(); os.fsync(f.fileno())
        return added


# ---- time --------------------------------------------------------------------------------------------------

def parse_duration(s):
    """'30s', '5m', '2h', '1d' (or a bare number of minutes) -> seconds."""
    m = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", s)
    if not m or int(m.group(1)) == 0:
        raise ValueError(f"bad duration {s!r} (use 30s, 5m, 2h, 1d)")
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400, "": 60}[m.group(2)]


def parse_local(s, now=None, roll=True):
    """'YYYY-MM-DD HH:MM' or 'HH:MM' (local time) -> epoch seconds. A bare 'HH:MM' that has passed today means
    tomorrow when roll=True."""
    now = now or time.time()
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            pass
    try:
        t = datetime.strptime(s, "%H:%M").time()
    except ValueError:
        raise ValueError(f"bad time {s!r} (use HH:MM or YYYY-MM-DD HH:MM, local time)")
    at = datetime.combine(datetime.fromtimestamp(now).date(), t).timestamp()
    return at + 86400 if roll and at <= now else at


def fmt_local(epoch, now=None):
    d = datetime.fromtimestamp(epoch)
    today = datetime.fromtimestamp(now or time.time()).date()
    return d.strftime("%H:%M") if d.date() == today else d.strftime("%m-%d %H:%M")
