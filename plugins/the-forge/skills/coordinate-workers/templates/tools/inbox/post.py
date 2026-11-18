"""Append one event to events.jsonl (deduped on source + id). Prints the new seq, or "duplicate".

  python3 -I post.py --source manual --priority high --text "check !45" [--kind note]
                     [--link URL] [--id ID]

Without --id every call adds a new event. Other scripts import common.post_events instead.
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--kind", default="note")
    p.add_argument("--priority", choices=list(common.PRIORITIES), default="normal")
    p.add_argument("--text", required=True)
    p.add_argument("--link", default="")
    p.add_argument("--id")
    a = p.parse_args(argv)
    added = common.post_events([common.make_event(a.source, a.kind, a.priority, a.text, a.link, a.id)])
    print(added[0]["seq"] if added else "duplicate")


if __name__ == "__main__":
    main()
