"""Nightly update: fast-forward the server's copy of the repo to what was merged on GitHub.

Only ever fast-forwards. If someone edited a tracked file on the server, or the server's branch
went its own way, it changes nothing and says what to do. After a pull it runs the drafter on the
fishing mug idea with the new code, so a broken merge shows up in the morning email instead of in
Monday's research run. It never pushes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SMOKE_IDEA = "ideas/papas-keepers-mug.toml"


class GitError(RuntimeError):
    pass


def git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {(p.stderr or p.stdout).strip()}")
    return p.stdout.rstrip("\n")


def smoke_test(root: Path) -> str | None:
    """Run the new code once. Returns None when it works, else what went wrong."""
    with tempfile.TemporaryDirectory() as out:
        p = subprocess.run(
            [sys.executable, "-m", "dbc", "--json", "draft", SMOKE_IDEA, "--out", out],
            cwd=root, capture_output=True, text=True, timeout=120,
        )
    if p.returncode != 0:
        return (p.stderr or p.stdout).strip()[-800:] or f"exit code {p.returncode}"
    try:
        result = json.loads(p.stdout)
    except ValueError:
        return f"the drafter printed something that isn't JSON: {p.stdout[:300]}"
    if not result.get("ok"):
        return "the fishing mug draft now fails its checks: " + "; ".join(
            f"{e['field']}: {e['message']}" for e in result.get("errors", []))
    return None


def _email(alert_to: str, alert_from: str, subject: str, lines: list[str]) -> dict:
    return {"send": True, "to": alert_to, "from": alert_from or alert_to,
            "subject": subject, "text": "\n".join(lines) + "\n"}


def run(root: Path, alert_to: str = "", alert_from: str = "", dry_run: bool = False) -> dict:
    """Fetch and fast-forward. Emails only when new code arrived or something needs John."""
    out = {"ok": True, "command": "update", "updated": False, "before": None, "after": None,
           "commits": [], "changed_files": [], "reimport": [], "error": None,
           "email": {"send": False}}
    fix = f"In the xCloud terminal: cd {root} && git status"
    try:
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        out["before"] = git(root, "rev-parse", "--short", "HEAD")
        dirty = git(root, "status", "--porcelain", "--untracked-files=no")
        if dirty:
            files = [line[3:] for line in dirty.splitlines()]
            raise GitError(
                "files were edited on the server, so the update was skipped to keep your edits: "
                + ", ".join(files) + ". If you don't need those edits: git checkout -- " + " ".join(files))
        git(root, "fetch", "--quiet", "origin")
        upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        ahead, behind = (int(n) for n in git(root, "rev-list", "--left-right", "--count", f"HEAD...{upstream}").split())
        if ahead:
            raise GitError(f"the server's {branch} branch has {ahead} commit(s) GitHub doesn't, so it can't "
                           f"fast-forward. If they aren't needed: git reset --hard {upstream}")
        if not behind:
            return out                                   # nothing new: stay quiet
        out["commits"] = git(root, "log", "--format=%h %s", f"HEAD..{upstream}").splitlines()
        out["changed_files"] = git(root, "diff", "--name-only", f"HEAD..{upstream}").splitlines()
        out["reimport"] = [f for f in out["changed_files"] if f.startswith("n8n/") and f.endswith(".json")]
        if dry_run:
            out["after"] = git(root, "rev-parse", "--short", upstream)
            return out
        git(root, "merge", "--ff-only", "--quiet", upstream)
        out["after"] = git(root, "rev-parse", "--short", "HEAD")
        out["updated"] = True
    except (GitError, subprocess.TimeoutExpired, OSError) as e:
        out.update(ok=False, error=str(e))
        out["email"] = _email(alert_to, alert_from, "Dinner Bell Co: nightly update needs you",
                              ["The nightly update didn't run:", "", str(e), "", fix])
        return out

    lines = [f"The server picked up {len(out['commits'])} new commit(s) from GitHub "
             f"({out['before']} → {out['after']}):", ""]
    lines += [f"  {c}" for c in out["commits"]]
    problem = smoke_test(root)
    if problem:
        out.update(ok=False, error=f"after the update the drafter fails: {problem}")
        lines += ["", "⚠️ After the update the drafter test failed:", problem, "",
                  f"To go back to the old version until it's fixed: cd {root} && git reset --hard {out['before']}",
                  "(the next nightly update will bring the new version back, so tell Claude about it)"]
    else:
        lines += ["", "The drafter still works with the new code."]
    if out["reimport"]:
        lines += ["", "These n8n workflows changed. Re-import them in n8n (Workflows → Import from file, "
                  "replace the old one, pick the email credential again, turn it back on):"]
        lines += [f"  {f}" for f in out["reimport"]]
    if ".env.example" in out["changed_files"]:
        lines += ["", "The list of keys (.env.example) changed: compare it with ~/.config/dinnerbellco/.env."]
    subject = "Dinner Bell Co: server updated" + (", but the drafter test failed" if problem else "")
    if out["reimport"] and not problem:
        subject += f" ({len(out['reimport'])} workflow(s) to re-import)"
    out["email"] = _email(alert_to, alert_from, subject, lines)
    return out
