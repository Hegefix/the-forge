#!/usr/bin/env python3
"""Token meter: sums Claude Code usage from the local transcripts and gates new work against a weekly budget.

Reads ~/.claude/projects/**/*.jsonl (sessions, subagents), dedupes each API response by
(message.id, requestId), and adds input, cache write, cache read and output tokens, weighted to
Opus-equivalent by model (budget.json "weights"). The headless helpers keep no transcript, so their
state/runs.log lines are added too (priced at the model on the line, in the helper's configured timezone).
Days and weeks use local time; a week starts at budget.json "week_resets". Parsed transcripts are cached per
file in state/cache.json (keyed by size and mtime; only the appended part is parsed again).

  meter.py report [--days 14]   per-day table, per-week totals, by role and model
  meter.py today                one line: today's and this week's Opus-equivalent tokens
  meter.py window FROM TO       tokens between two local times 'YYYY-MM-DD HH:MM' (for calibration)
  meter.py gate                 GREEN / YELLOW / RED for today, with an adaptive share of the week
  meter.py --self-check         tests on made-up transcripts

Gate: the week's budget minus the reserve, minus what the week used before today, is spread over the workdays
left (today included; with none left, over the days left in the week). YELLOW at day_yellow of that share, RED at day_red of it or at week_red of the week.
Real usage: when state/rate_limits.json (written by statusline.sh) is under 30 minutes old and the plan's weekly
% is 5 or more, the gate rescales the weekly limit to it, prints "(real)" and adds the 5-hour %; else "(est)".
Exit code: 0 with a verdict on the first word of the last line; 2 if budget.json is missing or not filled in.
The workspace is the folder three levels above this script, or WORKSPACE.
"""
import glob
import json
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.abspath(os.environ.get("WORKSPACE") or os.path.join(HERE, "..", "..", ".."))
ROOT = os.environ.get("METER_PROJECTS") or os.path.expanduser("~/.claude/projects")
# Claude Code names a project folder after its cwd, every character except letters and digits turned into '-'.
PREFIX = re.sub(r"[^A-Za-z0-9]", "-", WORKSPACE)
RUNLOG = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) .*\| in ([0-9.]+)k \(cache read ([0-9.]+)k\) out ([0-9.]+)k")
RUNLOG_MODEL = re.compile(r"\| model (\S+) \|")
RATE_LIMITS = os.environ.get("METER_RATE_LIMITS") or os.path.join(HERE, "state", "rate_limits.json")
CACHE = os.environ.get("METER_CACHE") or os.path.join(HERE, "state", "cache.json")


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


def parse_new(path, entry):
    """Append the unique-by-line usage records found after entry["offset"]; stop at a half-written last line."""
    with open(path, "rb") as fh:
        fh.seek(entry["offset"])
        for raw in fh:
            if not raw.endswith(b"\n"):
                break
            entry["offset"] += len(raw)
            if b'"usage"' not in raw or b'"assistant"' not in raw:
                continue
            try:
                o = json.loads(raw)
                m = o.get("message") or {}
                u = m.get("usage")
                if not u or o.get("type") != "assistant":
                    continue
                ts = datetime.fromisoformat(o["timestamp"].replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            entry["recs"].append([m.get("id"), o.get("requestId"), ts, m.get("model") or "?", *tok(u)])


def load_cache():
    try:
        return json.load(open(CACHE))
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + f".{os.getpid()}.tmp"
        json.dump(cache, open(tmp, "w"))
        os.replace(tmp, CACHE)
    except OSError:
        pass  # a cache that cannot be written only costs time


def records(since):
    seen = set()
    cutoff = since.timestamp() - 86400
    cache, fresh = load_cache(), {}
    for path in glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True):
        try:
            st = os.stat(path)
        except OSError:
            continue
        if st.st_mtime < cutoff:
            continue
        entry = cache.get(path)
        if not entry or st.st_size < entry["offset"]:  # new file, or rewritten shorter: parse from the start
            entry = {"offset": 0, "recs": []}
        if st.st_size > entry["offset"]:
            try:
                parse_new(path, entry)
            except OSError:
                continue
        entry["size"], entry["mtime"] = st.st_size, st.st_mtime
        fresh[path] = entry
        rel = os.path.relpath(path, ROOT).split(os.sep)
        r = role(os.path.join(ROOT, rel[0])) + ("/sub" if "subagents" in rel else "")
        for mid, rid, ts, model, *u in entry["recs"]:
            if (mid, rid) in seen:
                continue
            seen.add((mid, rid))
            t = datetime.fromtimestamp(ts)
            if t >= since:
                yield t, r, model, dict(zip(("input_tokens", "cache_creation_input_tokens",
                                             "cache_read_input_tokens", "output_tokens"), u))
    if fresh != cache:
        save_cache(fresh)


def helper_zone(runlog):
    """The timezone in the helper's config.json (comms-watch and scribe stamp runs.log in it); None = local."""
    try:
        name = json.load(open(os.path.join(os.path.dirname(os.path.dirname(runlog)), "config.json"))).get("timezone")
        return ZoneInfo(name) if name else None
    except Exception:
        return None


def helper_records(since):
    """Headless passes leave no transcript; their runs.log lines carry the tokens and the model."""
    try:
        default = load_cfg().get("helper_model") or "sonnet"
    except BudgetError:
        default = "sonnet"
    for path in glob.glob(os.path.join(WORKSPACE, "coordination", "tools", "*", "state", "runs.log")):
        helper = os.path.basename(os.path.dirname(os.path.dirname(path)))
        zone = helper_zone(path)
        for line in open(path, errors="replace"):
            m = RUNLOG.search(line)
            if not m:
                continue
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
            if zone:
                t = t.replace(tzinfo=zone).astimezone().replace(tzinfo=None)
            if t < since:
                continue
            tin, cr, out = (float(m.group(i)) * 1000 for i in (2, 3, 4))
            model = RUNLOG_MODEL.search(line)
            yield t, helper + "/headless", model.group(1) if model else default, {
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


def real_usage(cfg, now):
    """(weekly limit, 5-hour text) from the statusLine's rate_limits when fresh, else (None, "").

    The percentage was measured at `saved_at`, so the limit is the tokens used up to that moment
    divided by it, not the live total. A reading whose week has already reset is dropped.
    """
    try:
        rl = json.load(open(RATE_LIMITS))
        saved = float(rl["saved_at"])
        if now.timestamp() - saved > 1800:
            return None, ""
        limits = rl["rate_limits"]
        seven = limits.get("seven_day") or {}
        if "resets_at" in seven and float(seven["resets_at"]) <= now.timestamp():
            return None, ""
        weekly = None
        real = float(seven["used_percentage"]) / 100
        if real >= 0.05:  # a small % is too coarse to rescale by
            saved_dt = datetime.fromtimestamp(saved)
            ws = week_start(saved_dt, cfg["week_resets"])
            used = sum(sum(tok(u)) * weight(model, cfg["weights"])
                       for t, r, model, u in all_records(ws) if ws <= t <= saved_dt)
            if used > 0:
                weekly = used / real
        five = limits.get("five_hour") or {}
        return weekly, (f" | 5h {float(five['used_percentage']):.0f}%" if "used_percentage" in five else "")
    except (OSError, ValueError, KeyError, TypeError):
        return None, ""


def gate(now=None):
    cfg = load_cfg()
    now = now or datetime.now()
    td, before, ws = usage_now(cfg, now)
    weekly, five = real_usage(cfg, now)
    src = "real" if weekly else "est"
    weekly = weekly or cfg["weekly_opus_eq"]
    budget = weekly * (1 - cfg["reserve"])
    end = ws + timedelta(days=7)
    days = [now + timedelta(days=i) for i in range((end.date() - now.date()).days + 1)]
    days = [d for d in days if d < end]
    left = sum(1 for d in days if d.weekday() in cfg["workdays"]) or len(days) or 1
    day_budget = max(budget - before, 0) / left
    week_used = (before + td) / weekly
    day_used = td / day_budget if day_budget else 1.0
    verdict = "GREEN"
    if day_used >= cfg["day_yellow"]:
        verdict = "YELLOW"
    if day_used >= cfg["day_red"] or week_used >= cfg["week_red"]:
        verdict = "RED"
    return (f"{verdict} | today {td / 1e6:.0f}M of {day_budget / 1e6:.0f}M ({day_used:.0%}) | "
            f"week {week_used:.0%} ({src}) of {weekly / 1e9:.2f}B{five} | workdays left {left}")


def today():
    cfg = load_cfg()
    td, before, ws = usage_now(cfg, datetime.now())
    print(f"today {td:.0f} week {before + td:.0f} week_start {ws:%Y-%m-%d %H:%M}")


def self_check():
    """Made-up transcripts in a throwaway projects folder: dedupe, weights, the gate's three verdicts."""
    global ROOT, CACHE, WORKSPACE, RATE_LIMITS
    now = datetime.now().replace(microsecond=0)
    with tempfile.TemporaryDirectory() as tmp:
        proj = os.path.join(tmp, "projects", PREFIX + "--worktrees-repo-task")
        os.makedirs(proj)
        ROOT = os.path.join(tmp, "projects")
        os.environ["METER_BUDGET"] = os.path.join(tmp, "budget.json")
        CACHE = os.path.join(tmp, "state", "cache.json")
        WORKSPACE = os.path.join(tmp, "ws")
        RATE_LIMITS = os.path.join(tmp, "state", "rate_limits.json")

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
        # Nothing but non-workdays left: the remainder is spread over the days left in the week, not given to today.
        budget(10_000_000, workdays=[])
        days_left = (week_start(now) + timedelta(days=7) - now.replace(hour=0, minute=0, second=0)).days
        assert f"workdays left {days_left}" in gate(), gate()

        # Real usage: a fresh rate_limits.json rescales the weekly limit (1600 used = 40 % -> 4000); a stale or small one is ignored.
        def limits(age, week_pct, resets_in=86400):
            os.makedirs(os.path.dirname(RATE_LIMITS), exist_ok=True)
            json.dump({"saved_at": time.time() - age, "rate_limits": {"seven_day": {
                "used_percentage": week_pct, "resets_at": time.time() + resets_in},
                "five_hour": {"used_percentage": 12.4}}}, open(RATE_LIMITS, "w"))
        budget(10_000_000)
        limits(0, 40)  # saved just after the 1600 were spent
        line = gate()
        assert "week 40% (real) of 0.00B | 5h 12%" in line, line
        # Tokens spent after the reading must not inflate the limit: it stays 4000, so the week share grows.
        rec2 = {"type": "assistant", "timestamp": (now + timedelta(seconds=30)).astimezone().isoformat(),
                "requestId": "late", "message": {"id": "late", "model": "claude-opus-5-5", "usage": {"output_tokens": 400}}}
        with open(os.path.join(proj, "s.jsonl"), "a") as fh:
            fh.write(json.dumps(rec2) + "\n")
        assert "week 50% (real)" in gate(now + timedelta(seconds=60)), gate(now + timedelta(seconds=60))
        limits(3600, 40)
        assert "(est)" in gate() and "5h" not in gate(), gate()
        limits(60, 2)
        assert "(est)" in gate(), gate()
        limits(60, 40, resets_in=-5)  # the plan week has already reset: the old reading is dropped
        assert "(est)" in gate(), gate()
        os.remove(RATE_LIMITS)
        assert "(est)" in gate(), gate()

        # The cache holds the parsed file; a later append is picked up, a repeated response is still counted once.
        assert os.path.exists(CACHE)
        before = sum(sum(tok(u)) for *_, u in records(now - timedelta(hours=1)))
        rec = {"type": "assistant", "timestamp": now.astimezone().isoformat(), "requestId": "r9",
               "message": {"id": "m9", "model": "claude-opus-5-5", "usage": {"output_tokens": 500}}}
        with open(os.path.join(proj, "s.jsonl"), "a") as fh:
            fh.write(json.dumps(rec) + "\n" + json.dumps(rec)[:40])  # a complete line and a half-written one
        assert sum(sum(tok(u)) for *_, u in records(now - timedelta(hours=1))) == before + 500
        with open(os.path.join(proj, "s.jsonl"), "a") as fh:
            fh.write(json.dumps(rec)[40:] + "\n")  # the half line completes: the same response, counted once
        assert sum(sum(tok(u)) for *_, u in records(now - timedelta(hours=1))) == before + 500

        # Helper runs: priced at the model on the line, stamped in the helper's own timezone.
        helper = os.path.join(WORKSPACE, "coordination", "tools", "comms-watch")
        os.makedirs(os.path.join(helper, "state"))
        json.dump({"timezone": "Pacific/Kiritimati"}, open(os.path.join(helper, "config.json"), "w"))
        stamp = datetime.now(ZoneInfo("Pacific/Kiritimati")).strftime("%Y-%m-%d %H:%M")
        open(os.path.join(helper, "state", "runs.log"), "w").write(
            f"{stamp} | ok | 5s | $0.10 | model opus | in 10k (cache read 4k) out 1.0k | turns 3\n"
            f"{stamp} | ok | 5s | $0.10 | in 10k (cache read 4k) out 1.0k | turns 3\n")  # no model: helper_model
        budget(10_000_000, helper_model="haiku")
        runs = list(helper_records(now - timedelta(hours=1)))
        assert [r[2] for r in runs] == ["opus", "haiku"], runs
        assert abs((runs[0][0] - now).total_seconds()) < 120, runs[0][0]  # converted to this machine's time

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
