# Blocks until a new file appears in one of the watched directories, prints it, exits 0. Start it again after
# each wake-up. One waiter covers both helpers:
#   python3 -I wait_digest.py                     # the comms watcher's digests: $STATE_DIR/digests (default state/digests)
#   python3 -I wait_digest.py <dir> [<dir> …]     # any directories of notice files named so they sort by time,
#                                                 # e.g. comms-watch/state/digests scribe/state/notices
# Each <dir>/.seen keeps the last file printed, so a file written while nobody was waiting is printed at once
# on the next start. Files starting with "." are ignored (writers write .<name>.tmp, then rename).
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
dirs = [os.path.abspath(d) for d in sys.argv[1:]] or [
    os.path.join(os.environ.get("STATE_DIR") or os.path.join(HERE, "state"), "digests")]


def files(d):
    return sorted(f for f in os.listdir(d) if not f.startswith(".") and os.path.isfile(os.path.join(d, f)))


def mark(d, name):
    with open(os.path.join(d, ".seen"), "w") as f:
        f.write(name + "\n")


seen = {}
for d in dirs:
    os.makedirs(d, exist_ok=True)
    try:
        with open(os.path.join(d, ".seen")) as f:
            seen[d] = f.read().strip()
    except FileNotFoundError:
        existing = files(d)
        seen[d] = existing[-1] if existing else ""
        mark(d, seen[d])

while True:
    printed = False
    for d in dirs:
        new = [f for f in files(d) if f > seen[d]]
        for name in new:
            with open(os.path.join(d, name)) as f:
                label = name if len(dirs) == 1 else os.path.relpath(os.path.join(d, name), os.path.dirname(HERE))
                print(f"== {label}\n{f.read().rstrip()}")
        if new:
            mark(d, new[-1])
            printed = True
    if printed:
        sys.exit(0)
    time.sleep(5)
