#!/usr/bin/env python3
"""Janitor: cleans up after the workers in <workspace>/.worktrees. A script, no model.

Rules:
1. A worktree whose branch belongs to one of your MRs that is merged or closed, with no open MR left for
   that branch: remove the worktree and its local branch, if the worktree has no uncommitted changes and
   no unpushed commits. A merged MR's remote branch is deleted too (closed MRs keep theirs).
2. Once a day, on the first pass after JANITOR_CLEAN_HOUR (default 19), or on the next pass if yesterday's
   clean was missed (laptop asleep or off): delete native build output (JANITOR_BUILD_DIRS) in worktrees
   nobody has touched for 24 hours. Rebuilds recreate it.
3. Never: a dirty worktree, unpushed commits, a branch without an MR (reviews, previews, spikes), someone
   else's MR, the default branch, or anything outside .worktrees. Those are reported, not touched.
4. Every action and every finding is appended to state/report.log, which the coordinator watches.

GitLab only: it asks `glab api` about each worktree's branch, on the host of the repo's `origin`.

Settings (environment):
  WORKSPACE            the workspace root (default: the folder that holds coordination/tools/janitor/)
  JANITOR_AUTHOR       your GitLab username (default: the user `glab` is logged in as on that host)
  JANITOR_CLEAN_HOUR   local hour after which the daily build clean runs (default 19)
  JANITOR_BUILD_DIRS   colon-separated build folders, relative to a worktree
                       (default ios/build:android/app/build:android/build:android/.gradle)

Usage: janitor.py --once [--dry-run]   one pass
       janitor.py --wait                block until report.log grows, then print the new lines
"""
import json, os, shutil, subprocess, sys, time, urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("WORKSPACE") or HERE.parents[2])
WT_ROOT = WORKSPACE / ".worktrees"
STATE = HERE / "state"
REPORT = STATE / "report.log"
CLEAN_HOUR = int(os.environ.get("JANITOR_CLEAN_HOUR", "19"))
BUILD_DIRS = (os.environ.get("JANITOR_BUILD_DIRS") or
              "ios/build:android/app/build:android/build:android/.gradle").split(":")
PROTECTED = ("main", "master", "develop", "HEAD")
_authors = {}


def sh(args, cwd=None, check=False):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()}")
    return r


def git(repo, *args):
    return sh(["git", "-C", str(repo), *args]).stdout.strip()


def report(lines, dry):
    if not lines:
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    prefix = "DRY " if dry else ""
    STATE.mkdir(parents=True, exist_ok=True)
    with REPORT.open("a") as f:
        for line in lines:
            f.write(f"{stamp} {prefix}{line}\n")
    for line in lines:
        print(prefix + line)


def remote_of(repo):
    """(host, project path) of the repo's origin, for SSH, scp-like and HTTPS URLs."""
    url = git(repo, "remote", "get-url", "origin")
    if "://" in url:
        host, _, path = url.split("://", 1)[1].partition("/")
        host = host.split("@")[-1].split(":")[0]
    else:
        host, _, path = url.partition(":")
        host = host.split("@")[-1]
    return host, path.strip("/").removesuffix(".git")


def author_on(host):
    if os.environ.get("JANITOR_AUTHOR"):
        return os.environ["JANITOR_AUTHOR"]
    if host not in _authors:
        r = sh(["glab", "api", "--hostname", host, "user"])
        _authors[host] = json.loads(r.stdout).get("username") if r.returncode == 0 else None
    return _authors[host]


def mrs_for(host, project, branch):
    """Every MR with this source branch, or None when GitLab can't be reached."""
    enc = urllib.parse.quote(project, safe="")
    q = urllib.parse.urlencode({"source_branch": branch, "state": "all", "per_page": 20})
    r = sh(["glab", "api", "--hostname", host, f"projects/{enc}/merge_requests?{q}"])
    if r.returncode != 0:
        return None
    return json.loads(r.stdout or "[]")


def gitdir_of(wt):
    return (wt / (wt / ".git").read_text().split("gitdir:")[1].strip()).resolve()


def worktrees():
    """(main repo, worktree path, branch) for every worktree under .worktrees/<repo>/<task>."""
    out = []
    for d in sorted(WT_ROOT.glob("*/*")):
        if not (d / ".git").is_file():
            continue
        main = gitdir_of(d).parent.parent.parent  # <main>/.git/worktrees/<name>
        out.append((main, d, git(d, "rev-parse", "--abbrev-ref", "HEAD")))
    return out


def unpushed(wt, head, mr_shas):
    if head in mr_shas:
        return 0
    return int(git(wt, "rev-list", "--count", "HEAD", "--not", "--remotes") or 0)


def last_touch(wt):
    """Newest mtime of the worktree's HEAD, index and HEAD reflog: a checkout, commit or stage."""
    gitdir = gitdir_of(wt)
    times = [p.stat().st_mtime for p in (gitdir / "HEAD", gitdir / "index", gitdir / "logs/HEAD") if p.exists()]
    return max(times) if times else 0


def remove_merged(dry):
    lines = []
    all_wts = worktrees()
    for main in {m for m, _, _ in all_wts}:
        sh(["git", "-C", str(main), "fetch", "-q", "--prune", "origin"])
    for main, wt, branch in all_wts:
        name = f"{wt.parent.name}/{wt.name} [{branch}]"
        if branch in PROTECTED:
            continue
        host, project = remote_of(main)
        mrs = mrs_for(host, project, branch)
        if mrs is None:
            lines.append(f"SKIP {name}: GitLab not reachable")
            continue
        author = author_on(host)
        if not author:
            lines.append(f"SKIP {name}: no GitLab username for {host}; set JANITOR_AUTHOR")
            continue
        ours = [m for m in mrs if m["author"]["username"] == author]
        if not ours:
            continue  # no MR of ours: left alone, listed in the daily summary
        if any(m["state"] in ("opened", "locked") for m in ours):
            continue
        dirty = git(wt, "status", "--porcelain")
        n = unpushed(wt, git(wt, "rev-parse", "HEAD"), {m["sha"] for m in ours if m.get("sha")})
        mr = max(ours, key=lambda m: m["updated_at"])
        ref = f"{project}!{mr['iid']} {mr['state']}"
        if dirty:
            lines.append(f"KEEP {name}: {ref}, but uncommitted changes; decide")
            continue
        if n:
            lines.append(f"KEEP {name}: {ref}, but {n} unpushed commit(s); decide")
            continue
        if not dry:
            sh(["git", "-C", str(main), "worktree", "remove", str(wt)], check=True)
            sh(["git", "-C", str(main), "branch", "-D", branch])
        lines.append(f"REMOVED worktree {name} ({ref})")
        if mr["state"] == "merged" and git(main, "ls-remote", "--heads", "origin", branch):
            if not dry:
                sh(["git", "-C", str(main), "push", "origin", "--delete", branch])
            lines.append(f"REMOVED remote branch {project}:{branch} ({ref})")
    return lines


def clean_builds(dry):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    stamp_file = STATE / "last-build-clean"
    last_clean = stamp_file.read_text().strip() if stamp_file.exists() else ""
    # Due after the clean hour, or right away when yesterday's clean was missed.
    if last_clean == today or (now.hour < CLEAN_HOUR and last_clean >= yesterday):
        return []
    lines, freed = [], 0
    for main, wt, branch in worktrees():
        if time.time() - last_touch(wt) < 24 * 3600:
            continue
        for rel in BUILD_DIRS:
            p = wt / rel
            if p.exists():
                size = int(sh(["du", "-sk", str(p)]).stdout.split()[0]) * 1024
                if not dry:
                    shutil.rmtree(p, ignore_errors=True)
                freed += size
                lines.append(f"CLEANED {wt.parent.name}/{wt.name}/{rel} ({size // 2**20} MB)")
    no_mr = []
    for main, wt, branch in worktrees():
        if branch in PROTECTED:
            continue
        host, project = remote_of(main)
        if mrs_for(host, project, branch) == []:
            no_mr.append(f"{wt.parent.name}/{wt.name} [{branch}]")
    if no_mr:
        lines.append("NO-MR worktrees (left alone, decide): " + ", ".join(no_mr))
    lines.append(f"DAILY build clean done, freed {freed // 2**30} GB")
    if not dry:
        STATE.mkdir(parents=True, exist_ok=True)
        stamp_file.write_text(today)
    return lines


def pass_once(dry):
    if not WT_ROOT.is_dir():
        sys.exit(f"STOP: no {WT_ROOT}; set WORKSPACE to the workspace root")
    report(remove_merged(dry) + clean_builds(dry), dry)


def wait():
    STATE.mkdir(parents=True, exist_ok=True)
    REPORT.touch()
    start = REPORT.stat().st_size
    while REPORT.stat().st_size == start:
        time.sleep(30)
    time.sleep(2)
    with REPORT.open() as f:
        f.seek(start)
        print(f.read(), end="")


if __name__ == "__main__":
    if "--wait" in sys.argv:
        wait()
    elif "--once" in sys.argv:
        pass_once("--dry-run" in sys.argv)
    else:
        print(__doc__)
