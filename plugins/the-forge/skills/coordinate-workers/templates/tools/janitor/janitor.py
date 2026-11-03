#!/usr/bin/env python3
"""Janitor: cleans up after the workers in <workspace>/.worktrees. A script, no model.

Rules:
1. A worktree whose branch belongs to one of your MRs that is merged or closed, with no open MR left for
   that branch: remove the worktree and its local branch, if the worktree has no uncommitted changes and
   its HEAD is that MR's head commit. A merged MR's remote branch is deleted too (closed MRs keep theirs).
2. Once a day, on the first pass after JANITOR_CLEAN_HOUR (default 19), or on the next pass if yesterday's
   clean was missed (laptop asleep or off): delete native build output (JANITOR_BUILD_DIRS) in worktrees
   nobody has touched for 24 hours. Rebuilds recreate it.
3. Never: a dirty worktree, a HEAD that is not a merged or closed MR's head (new commits, or a new task on
   a reused branch name), a branch without an MR (reviews, previews, spikes), someone else's MR, the
   default branch, or anything outside .worktrees. Those are reported, not touched.
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
       janitor.py --self-check          its tests: one pass on a throwaway repo, with a stub glab
"""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, time, urllib.parse
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
        head = git(wt, "rev-parse", "HEAD")
        # Only an MR whose head is this HEAD counts: an older MR on a reused branch name doesn't.
        done = [m for m in ours if m.get("sha") == head]
        mr = max(done or ours, key=lambda m: m["updated_at"])
        ref = f"{project}!{mr['iid']} {mr['state']}"
        if git(wt, "status", "--porcelain"):
            lines.append(f"KEEP {name}: {ref}, but uncommitted changes; decide")
            continue
        if not done:
            lines.append(f"KEEP {name}: {ref}, but HEAD {head[:8]} is not the head of a merged or closed MR "
                         "(new commits, or a new task on a reused branch name); decide")
            continue
        if not dry:
            r = sh(["git", "-C", str(main), "worktree", "remove", str(wt)])
            if r.returncode != 0:  # locked, submodules: report it and go on with the pass
                lines.append(f"KEEP {name}: {ref}, but worktree remove failed: {' '.join(r.stderr.split())}; decide")
                continue
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


def self_check():
    """One real pass on a throwaway repo, origin and worktrees, with a stub glab. Touches nothing else."""
    global WT_ROOT, STATE, REPORT
    tmp = Path(tempfile.mkdtemp(prefix="janitor-check-")).resolve()
    try:
        os.environ.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "JANITOR_AUTHOR": "me",
                           "JANITOR_CHECK_MRS": str(tmp / "mrs.json"),
                           "PATH": f"{tmp / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"})
        for who in ("AUTHOR", "COMMITTER"):
            os.environ[f"GIT_{who}_NAME"], os.environ[f"GIT_{who}_EMAIL"] = "check", "check@example.com"
        (tmp / "bin").mkdir()
        stub = tmp / "bin/glab"  # answers `glab api .../merge_requests?source_branch=<b>` from mrs.json
        stub.write_text("#!/usr/bin/env python3\nimport json, os, sys, urllib.parse\n"
                        "q = urllib.parse.parse_qs(urllib.parse.urlsplit(sys.argv[-1]).query)\n"
                        "mrs = json.load(open(os.environ['JANITOR_CHECK_MRS']))\n"
                        "print(json.dumps(mrs.get(q['source_branch'][0], [])))\n")
        stub.chmod(0o755)
        WT_ROOT, STATE = tmp / ".worktrees", tmp / "state"
        REPORT = STATE / "report.log"
        origin, main = tmp / "origin.git", tmp / "app"
        sh(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        sh(["git", "init", "-q", "-b", "main", str(main)], check=True)
        sh(["git", "-C", str(main), "remote", "add", "origin", origin.as_uri()], check=True)
        sh(["git", "-C", str(main), "commit", "-q", "--allow-empty", "-m", "base"], check=True)
        sh(["git", "-C", str(main), "push", "-q", "origin", "main"], check=True)

        def worktree(task, branch):
            """A worker's worktree as launch-worker.sh makes it, with one pushed commit."""
            wt = WT_ROOT / "app" / task
            sh(["git", "-C", str(main), "worktree", "add", "-q", "--no-track", "-b", branch, str(wt), "origin/main"],
               check=True)
            sh(["git", "-C", str(wt), "commit", "-q", "--allow-empty", "-m", task], check=True)
            sh(["git", "-C", str(wt), "push", "-q", "origin", branch], check=True)
            return wt, git(wt, "rev-parse", "HEAD")

        def mr(iid, state, sha):
            return {"iid": iid, "state": state, "sha": sha, "author": {"username": "me"},
                    "updated_at": f"2026-01-{iid:02d}T00:00:00Z"}

        ahead, ahead_head = worktree("ahead", "feat-ahead")
        sh(["git", "-C", str(ahead), "commit", "-q", "--allow-empty", "-m", "after the merge"], check=True)
        locked, locked_head = worktree("locked", "feat-locked")
        sh(["git", "-C", str(main), "worktree", "lock", str(locked)], check=True)  # `worktree remove` refuses it
        merged, merged_head = worktree("merged", "feat-done")
        reused, _ = worktree("reused", "fix-login")
        old_login = git(main, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "an earlier fix-login")
        (tmp / "mrs.json").write_text(json.dumps({
            "feat-ahead": [mr(2, "merged", ahead_head)],
            "feat-done": [mr(3, "merged", merged_head)],
            "feat-locked": [mr(4, "merged", locked_head)],
            "fix-login": [mr(7, "merged", old_login)],  # an earlier task on the same branch name
        }))

        with contextlib.redirect_stdout(io.StringIO()):
            pass_once(dry=False)
        out = REPORT.read_text()
        lines = [l.split(" ", 2)[2] for l in out.splitlines()]  # without the timestamp

        def has(repo, ref):
            return sh(["git", "-C", str(repo), "rev-parse", "-q", "--verify", ref]).returncode == 0

        # A merged MR whose head is the worktree's HEAD: the worktree and both branches go.
        assert any(l.startswith("REMOVED worktree app/merged [feat-done]") for l in lines), out
        assert not merged.exists() and not has(main, "refs/heads/feat-done"), out
        assert not git(main, "ls-remote", "--heads", "origin", "feat-done"), out
        # A worktree git won't remove (locked, submodules): kept with git's error, and the pass goes on.
        assert any(l.startswith("KEEP app/locked [feat-locked]") and "worktree remove failed" in l for l in lines), out
        assert locked.is_dir() and has(main, "refs/heads/feat-locked"), out
        assert git(main, "ls-remote", "--heads", "origin", "feat-locked"), out
        assert any(l.startswith("DAILY build clean done") for l in lines), out
        # A commit after the merge: kept, and reported.
        assert any(l.startswith("KEEP app/ahead [feat-ahead]") for l in lines), out
        assert ahead.is_dir() and has(main, "refs/heads/feat-ahead"), out
        # A new task on a reused branch name, with only an old merged MR at another commit: kept, and reported.
        assert any(l.startswith("KEEP app/reused [fix-login]") for l in lines), out
        assert reused.is_dir() and has(main, "refs/heads/fix-login"), out
        assert git(main, "ls-remote", "--heads", "origin", "fix-login"), out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("self-check ok")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        self_check()
    elif "--wait" in sys.argv:
        wait()
    elif "--once" in sys.argv:
        pass_once("--dry-run" in sys.argv)
    else:
        print(__doc__)
