#!/usr/bin/env python3
"""Token meter: sums Claude Code usage from the local transcripts and gates new work against a weekly budget.

Reads ~/.claude/projects/**/*.jsonl (sessions, subagents), dedupes each API response by
(message.id, requestId), and adds input, cache write, cache read and output tokens, weighted to
Opus-equivalent by model (budget.json "weights"). The headless helpers keep no transcript, so their
state/runs.log lines are added too. Days and weeks use local time; a week starts at budget.json "week_resets".

  meter.py report [--days 14]   per-day table, per-week totals, by role and model
  meter.py today                one line: today's and this week's Opus-equivalent tokens
  meter.py window FROM TO       tokens between two local times 'YYYY-MM-DD HH:MM' (for calibration)
  meter.py gate                 GREEN / YELLOW / RED for today, with an adaptive share of the week
  meter.py --self-check         tests on made-up transcripts

Gate: the week's budget minus the reserve, minus what the week used before today, is spread over the workdays
left (today included). YELLOW at day_yellow of that share, RED at day_red of it or at week_red of the week.
Exit code: 0 with a verdict on the first word of the last line; 2 if budget.json is missing or not filled in.
The workspace is the folder three levels above this script, or WORKSPACE.
"""
import glob
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.abspath(os.environ.get("WORKSPACE") or os.path.join(HERE, "..", "..", ".."))
ROOT = os.environ.get("METER_PROJECTS") or os.path.expanduser("~/.claude/projects")
# Claude Code names a project folder after its cwd, every character except letters and digits turned into '-'.
PREFIX = re.sub(r"[^A-Za-z0-9]", "-", WORKSPACE)
RUNLOG = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) .*\| in ([0-9.]+)k \(cache read ([0-9.]+)k\) out ([0-9.]+)k")


class BudgetError(Exception):
    pass


def load_cfg():
    try:
        cfg = json.load(open(os.environ.get("METER_BUDGET") or os.path.join(HERE, "budget.json")))
    except (OSError, ValueError) as e:
        raise BudgetError(f"budget.json unreadable: {e}")
    for key in ("weekly_opus_eq", "reserve", "day_yellow", "day_red", "week_red"):
        if not isinstance(cfg.get(key), (int, float)) or isinstance(cfg.get(key), bool):
            raise BudgetError(f"budget.json: {key} is not a number yet ({cfg.get(key)!r}); fill it in")
    if cfg["weekly_opus_eq"] <= 0:
        raise BudgetError("budget.json: weekly_opus_eq must be above 0")
    cfg.setdefault("week_resets", {"weekday": 0, "hour": 0})
    cfg.setdefault("workdays", [0, 1, 2, 3, 4])
    cfg.setdefault("weights", {"opus": 1.0, "sonnet": 0.6, "haiku": 0.2, "fable": 1.0})
    return cfg


def weights():
    try:
        return load_cfg()["weights"]
    except BudgetError:
        return {"opus": 1.0, "sonnet": 0.6, "haiku": 0.2, "fable": 1.0}


def role(project_dir):
    name = os.path.basename(project_dir)
    if name == PREFIX:
        return "coordinator"
    if name.startswith(PREFIX + "-coordination-tools"):
        return "helpers"
    if name.startswith(PREFIX + "--worktrees"):
        return "workers"
    return "other"


def records(since):
    seen = set()
    cutoff = since.timestamp() - 86400
    for path in glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(path) < cutoff:
                continue
        except OSError:
            continue
        rel = os.path.relpath(path, ROOT).split(os.sep)
        r = role(os.path.join(ROOT, rel[0])) + ("/sub" if "subagents" in rel else "")
        with open(path, "rb") as fh:
            for raw in fh:
                if b'"usage"' not in raw or b'"assistant"' not in raw:
                    continue
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                m = o.get("message") or {}
                u = m.get("usage")
                if not u or o.get("type") != "assistant":
                    continue
                key = (m.get("id"), o.get("requestId"))
                if key in seen:
                    continue
                seen.add(key)
                try:
                    t = datetime.fromisoformat(o["timestamp"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
                except Exception:
                    continue
                if t >= since:
                    yield t, r, (m.get("model") or "?"), u


def helper_records(since):
    """Headless passes leave no transcript; their runs.log lines carry the tokens."""
    try:
        model = load_cfg().get("helper_model") or "sonnet"
    except BudgetError:
        model = "sonnet"
    for path in glob.glob(os.path.join(WORKSPACE, "coordination", "tools", "*", "state", "runs.log")):
        helper = os.path.basename(os.path.dirname(os.path.dirname(path)))
        for line in open(path, errors="replace"):
            m = RUNLOG.search(line)
            if not m:
                continue
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
            if t < since:
                continue
            tin, cr, out = (float(m.group(i)) * 1000 for i in (2, 3, 4))
            yield t, helper + "/headless", model, {
                "input_tokens": tin - cr, "cache_read_input_tokens": cr, "output_tokens": out}


def all_records(since):
    yield from records(since)
    yield from helper_records(since)


def weight(model, table):
    for k, w in table.items():
        if k in (model or ""):
            return w
    return 1.0


def tok(u):
    return (u.get("input_tokens") or 0, u.get("cache_creation_input_tokens") or 0,
            u.get("cache_read_input_tokens") or 0, u.get("output_tokens") or 0)


def week_start(t, resets=None):
    resets = resets or {"weekday": 0, "hour": 0}
    d = t - timedelta(days=(t.weekday() - resets["weekday"]) % 7)
    s = d.replace(hour=resets["hour"], minute=0, second=0, microsecond=0)
    return s if s <= t else s - timedelta(days=7)


def fmt(n):
    return f"{n / 1e6:8.1f}M"


def report(days):
    cfg_w = weights()
    try:
        resets = load_cfg()["week_resets"]
    except BudgetError:
        resets = None
    since = (datetime.now() - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    day, byrole, bymodel = defaultdict(float), defaultdict(int), defaultdict(int)
    week, raw = defaultdict(float), defaultdict(int)
    for t, r, model, u in all_records(since):
        s = sum(tok(u))
        eq = s * weight(model, cfg_w)
        day[t.date()] += eq
        week[week_start(t, resets)] += eq
        raw[t.date()] += s
        byrole[r] += s
        bymodel[model] += s
    print("day           total  opus-eq")
    for d in sorted(day):
        print(f"{d} {d:%a} {fmt(raw[d])} {fmt(day[d])}")
    print("\nweek      opus-eq")
    for w in sorted(week):
        print(f"{w:%Y-%m-%d %a %H:%M} {fmt(week[w])}")
    print("\nby role:")
    for r, s in sorted(byrole.items(), key=lambda x: -x[1]):
        print(f"  {r:24s}{fmt(s)}")
    print("by model:")
    for m, s in sorted(bymodel.items(), key=lambda x: -x[1]):
        print(f"  {m:30s}{fmt(s)}")


def window(a, b):
    cfg_w = weights()
    since = datetime.strptime(a, "%Y-%m-%d %H:%M")
    until = datetime.strptime(b, "%Y-%m-%d %H:%M")
    tot, eq = 0, 0.0
    for t, r, model, u in all_records(since):
        if t <= until:
            s = sum(tok(u))
            tot += s
            eq += s * weight(model, cfg_w)
    print(f"{a} -> {b}: total {fmt(tot)} opus-eq {fmt(eq)}")


def usage_now(cfg, now):
    """(used today, used earlier this week), both Opus-equivalent."""
    ws = week_start(now, cfg["week_resets"])
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    before = td = 0.0
    for t, r, model, u in all_records(min(ws, d0)):
        if t < ws:
            continue
        s = sum(tok(u)) * weight(model, cfg["weights"])
        if t >= d0:
            td += s
        else:
            before += s
    return td, before, ws


def gate(now=None):
    cfg = load_cfg()
    now = now or datetime.now()
    td, before, ws = usage_now(cfg, now)
    budget = cfg["weekly_opus_eq"] * (1 - cfg["reserve"])
    end = ws + timedelta(days=7)
    left = sum(1 for i in range((end.date() - now.date()).days + 1)
               if (now + timedelta(days=i)).weekday() in cfg["workdays"] and (now + timedelta(days=i)) < end) or 1
    day_budget = max(budget - before, 0) / left
    week_used = (before + td) / cfg["weekly_opus_eq"]
    day_used = td / day_budget if day_budget else 1.0
    verdict = "GREEN"
    if day_used >= cfg["day_yellow"]:
        verdict = "YELLOW"
    if day_used >= cfg["day_red"] or week_used >= cfg["week_red"]:
        verdict = "RED"
    return (f"{verdict} | today {td / 1e6:.0f}M of {day_budget / 1e6:.0f}M ({day_used:.0%}) | "
            f"week {week_used:.0%} of {cfg['weekly_opus_eq'] / 1e9:.2f}B | workdays left {left}")


def today():
    cfg = load_cfg()
    td, before, ws = usage_now(cfg, datetime.now())
    print(f"today {td:.0f} week {before + td:.0f} week_start {ws:%Y-%m-%d %H:%M}")


def self_check():
    """Made-up transcripts in a throwaway projects folder: dedupe, weights, the gate's three verdicts."""
    global ROOT
    now = datetime.now().replace(microsecond=0)
    with tempfile.TemporaryDirectory() as tmp:
        proj = os.path.join(tmp, "projects", PREFIX + "--worktrees-repo-task")
        os.makedirs(proj)
        ROOT = os.path.join(tmp, "projects")
        os.environ["METER_BUDGET"] = os.path.join(tmp, "budget.json")

        def write(tokens_opus, tokens_sonnet=0):
            lines = []
            ts = now.astimezone().isoformat()
            for i, (model, n) in enumerate((("claude-opus-5-5", tokens_opus), ("claude-sonnet-5-5", tokens_sonnet))):
                if n:
                    rec = {"type": "assistant", "timestamp": ts, "requestId": f"r{i}",
                           "message": {"id": f"m{i}", "model": model, "usage": {"output_tokens": n}}}
                    lines += [json.dumps(rec)] * 2  # the same response twice: counted once
            open(os.path.join(proj, "s.jsonl"), "w").write("\n".join(lines) + "\n")

        def budget(weekly, **extra):
            cfg = {"weekly_opus_eq": weekly, "reserve": 0.1, "day_yellow": 0.7, "day_red": 0.9, "week_red": 0.9,
                   "week_resets": {"weekday": 0, "hour": 0}, "workdays": [0, 1, 2, 3, 4, 5, 6]}
            cfg.update(extra)
            json.dump(cfg, open(os.environ["METER_BUDGET"], "w"))

        # 1000 Opus + 1000 Sonnet = 1600 Opus-eq today. Budget 10000 a week, 7 days left or fewer.
        write(1000, 1000)
        budget(10_000_000)
        assert gate().startswith("GREEN"), gate()
        budget(10_000_000, workdays=[now.weekday()])  # today is the only workday left: 9000 share -> 18 %
        assert gate().startswith("GREEN"), gate()
        budget(2000, workdays=[now.weekday()])  # share 1800, used 1600 = 89 %
        assert gate().startswith("YELLOW"), gate()
        budget(1700, workdays=[now.weekday()])  # share 1530, used 105 %
        assert gate().startswith("RED"), gate()
        budget(100_000, week_red=0.01)  # the week's own limit wins
        assert gate().startswith("RED"), gate()
        budget("<fill in>")
        try:
            gate()
            raise AssertionError("a placeholder must be refused")
        except BudgetError:
            pass
    print("self-check ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    try:
        if cmd == "report":
            report(int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 14)
        elif cmd == "today":
            today()
        elif cmd == "window" and len(sys.argv) == 4:
            window(sys.argv[2], sys.argv[3])
        elif cmd == "gate":
            print(gate())
        elif cmd == "--self-check":
            self_check()
        else:
            print(__doc__)
    except BudgetError as e:
        print(f"CONFIG | {e}")
        sys.exit(2)
