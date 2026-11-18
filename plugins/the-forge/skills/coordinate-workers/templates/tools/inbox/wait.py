"""The coordinator's one waiter. Blocks until there is an unread event at or above --min, waits --batch seconds
so related events arrive together, prints the unread events, moves the cursor past them, exits 0.

  python3 -I wait.py                 # wake on high; then print unread high + normal
  python3 -I wait.py --min normal    # wake on normal too
  python3 -I wait.py --peek          # print unread now, don't block, don't move the cursor
  python3 -I wait.py --status        # unread counts, bridge alive?, timers, waiter armed?
  python3 -I wait.py --recent 30 --min low   # the last 30 events, read or not

Printed: one line per event at or above --show (default normal; never above --min), "time source priority text
link", then a count of the lower ones it passed over. The cursor (state/cursor, "<seq> <byte offset>") is
durable: an event posted while no waiter runs is printed by the next one. Exit 2: the bridge is not running (no
heartbeat for 3 minutes), so nothing new would come; start it with start.sh (--status exits 2 for this too).
Exit 3: another waiter is armed.
"""
import argparse, os, sys, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common, timer

CURSOR = os.path.join(common.STATE, "cursor")
STALE = 180  # seconds without a bridge heartbeat
POLL = float(os.environ.get("INBOX_POLL") or 5)  # seconds between looks at events.jsonl
P = common.PRIORITIES


def read_cursor():
    try:
        with open(CURSOR) as f:
            seq, off = f.read().split()
        return int(seq), int(off)
    except FileNotFoundError:
        return 0, 0


def unread(seq, off):
    """Events after `seq`, read from byte `off` (from the start if events.jsonl shrank). -> (events, end)."""
    size = os.path.getsize(common.EVENTS) if os.path.exists(common.EVENTS) else 0
    events, end = common.read_events(off if off <= size else 0)
    return [e for e in events if e["seq"] > seq], end


def bridge_age():
    try:
        with open(common.HEARTBEAT) as f:
            return time.time() - float(f.read().split()[0])
    except (FileNotFoundError, ValueError, IndexError):
        return None


def fmt(e, width):
    try:
        when = common.fmt_local(datetime.fromisoformat(e["ts"]).timestamp())
    except ValueError:
        when = e["ts"]
    text = " ⏎ ".join(e["text"].splitlines())
    if width and len(text) > width:
        text = text[:width - 1] + "…"
    return " ".join(x for x in (when, e["source"], e["priority"], text, e["link"]) if x)


def show(events, level, width):
    for e in events:
        if P[e["priority"]] >= P[level]:
            print(fmt(e, width))
    hidden = {k: sum(e["priority"] == k for e in events) for k in P if P[k] < P[level]}
    rest = ", ".join(f"{n} {k}" for k, n in hidden.items() if n)
    if rest:
        print(f"(+{rest} not shown)")


def status():
    seq, off = read_cursor()
    events, _ = unread(seq, off)
    counts = ", ".join(f"{k} {sum(e['priority'] == k for e in events)}" for k in reversed(list(P)))
    age = bridge_age()
    bridge = "NOT RUNNING (no heartbeat)" if age is None else (
        f"alive (heartbeat {max(age, 0):.0f}s ago)" if age < STALE else f"DOWN (last heartbeat {age / 60:.0f} min ago)")
    active = sum(t["status"] == "active" for t in timer.load()["timers"])
    with common.locked("wait", blocking=False) as free:
        armed = "no" if free else "yes"
    print(f"unread: {counts} | bridge {bridge} | timers active {active} | waiter armed: {armed}")
    if age is None or age >= STALE:
        sys.exit(2)


def bridge_down():
    age = bridge_age()
    if age is None or age >= STALE:
        why = "no heartbeat" if age is None else f"last heartbeat {age / 60:.0f} min ago"
        print(f"inbox: the bridge is not running or its passes fail ({why}); see "
              f"{os.path.join(common.STATE, 'bridge.log')}, start: {os.path.join(common.HERE, 'start.sh')}")
        return True
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--min", choices=list(P), default="high")
    p.add_argument("--show", choices=list(P), default="normal")
    p.add_argument("--peek", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--recent", type=int, metavar="N")
    p.add_argument("--batch", type=float, default=20, help="seconds to wait for more after the first hit")
    p.add_argument("--width", type=int, default=400, help="cut text to this many characters (0: no cut)")
    p.add_argument("--no-bridge-check", action="store_true", help="tests only")
    a = p.parse_args()
    level = min(a.show, a.min, key=P.get)
    if a.status:
        return status()
    if a.recent:
        events = [e for e in common.read_events()[0] if P[e["priority"]] >= P[a.min]]
        for e in events[-a.recent:]:
            print(fmt(e, a.width))
        return
    if a.peek:
        events, _ = unread(*read_cursor())
        return show(events, level, a.width) if events else print("no unread events")
    with common.locked("wait", blocking=False) as ok:
        if not ok:
            print("wait.py: another waiter is already armed (state/wait.lock)")
            sys.exit(3)
        while True:
            if not a.no_bridge_check and bridge_down():
                sys.exit(2)
            events, _ = unread(*read_cursor())
            if any(P[e["priority"]] >= P[a.min] for e in events):
                break
            time.sleep(POLL)
        time.sleep(a.batch)
        seq, off = read_cursor()
        events, end = unread(seq, off)
        if events:  # `end` is where the last complete line read ends: exactly the events printed
            show(events, level, a.width)
            common.write_atomic(CURSOR, f"{events[-1]['seq']} {end}\n")


if __name__ == "__main__":
    main()
