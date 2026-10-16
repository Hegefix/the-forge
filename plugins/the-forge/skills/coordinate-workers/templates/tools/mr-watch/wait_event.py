#!/usr/bin/env python3
"""For the coordinator, run in the background: blocks until mr-watch's events.log gets a new line, prints
the new lines and exits, which wakes the coordinator. Start it again after each wake-up."""
import os, sys, time

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.log")
open(p, "a").close()
size = os.path.getsize(p)
while True:
    time.sleep(5)
    s = os.path.getsize(p)
    if s > size:
        time.sleep(3)
        with open(p) as f:
            f.seek(size)
            print(f.read().strip())
        sys.exit(0)
