"""Nightly update: only ever fast-forwards, and says what to do when it can't."""

import shutil
import subprocess

import pytest

from dbc import config, updater

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def sh(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def commit(repo, path, text, msg):
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    sh(repo, "add", path)
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", msg)


@pytest.fixture
def repos(tmp_path):
    """A GitHub stand-in (origin), the server's clone, and a laptop clone to merge from."""
    origin = tmp_path / "origin.git"
    sh(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    laptop = tmp_path / "laptop"
    sh(tmp_path, "clone", "-q", str(origin), str(laptop))
    commit(laptop, "README.md", "hi\n", "first")
    sh(laptop, "push", "-q", "origin", "main")
    server = tmp_path / "server"
    sh(tmp_path, "clone", "-q", str(origin), str(server))
    return laptop, server


@pytest.fixture(autouse=True)
def no_smoke(monkeypatch):
    monkeypatch.setattr(updater, "smoke_test", lambda root: None)


def test_up_to_date_is_quiet(repos):
    _, server = repos
    out = updater.run(server, "john@example.com")
    assert out["ok"] and not out["updated"] and not out["email"]["send"]


def test_new_commits_fast_forward_and_name_workflows_to_reimport(repos):
    laptop, server = repos
    commit(laptop, "n8n/idea-research.json", "{}\n", "Add idea research workflow")
    commit(laptop, "dbc/x.py", "x = 1\n", "Add x")
    sh(laptop, "push", "-q", "origin", "main")
    out = updater.run(server, "john@example.com", "bot@example.com")
    assert out["ok"] and out["updated"] and len(out["commits"]) == 2
    assert (server / "dbc" / "x.py").exists()
    assert out["reimport"] == ["n8n/idea-research.json"]
    assert out["email"]["send"] and "1 workflow(s) to re-import" in out["email"]["subject"]
    assert out["email"]["from"] == "bot@example.com"
    assert not updater.run(server, "john@example.com")["email"]["send"]   # next night: quiet


def test_dry_run_changes_nothing(repos):
    laptop, server = repos
    commit(laptop, "a.txt", "a\n", "a")
    sh(laptop, "push", "-q", "origin", "main")
    out = updater.run(server, "j@example.com", dry_run=True)
    assert out["commits"] and not out["updated"] and not (server / "a.txt").exists()


def test_edits_on_the_server_are_never_overwritten(repos):
    laptop, server = repos
    commit(laptop, "README.md", "new\n", "change")
    sh(laptop, "push", "-q", "origin", "main")
    (server / "README.md").write_text("edited on the server\n")
    out = updater.run(server, "john@example.com")
    assert not out["ok"] and "edited on the server" in out["error"] and "README.md" in out["error"]
    assert (server / "README.md").read_text() == "edited on the server\n"
    assert out["email"]["send"] and "needs you" in out["email"]["subject"]


def test_untracked_files_like_state_and_inbox_dont_block(repos):
    laptop, server = repos
    (server / "state").mkdir()
    (server / "state" / "watch-orders.json").write_text("{}")
    commit(laptop, "b.txt", "b\n", "b")
    sh(laptop, "push", "-q", "origin", "main")
    assert updater.run(server, "john@example.com")["updated"]


def test_server_commits_stop_the_update(repos):
    laptop, server = repos
    commit(server, "local.txt", "x\n", "local")
    commit(laptop, "c.txt", "c\n", "c")
    sh(laptop, "push", "-q", "origin", "main")
    out = updater.run(server, "john@example.com")
    assert not out["ok"] and "can't fast-forward" in out["error"]


def test_broken_new_code_is_reported_with_the_way_back(repos, monkeypatch):
    laptop, server = repos
    commit(laptop, "d.txt", "d\n", "d")
    sh(laptop, "push", "-q", "origin", "main")
    monkeypatch.setattr(updater, "smoke_test", lambda root: "SyntaxError in dbc/cli.py")
    out = updater.run(server, "john@example.com")
    assert not out["ok"] and out["updated"]
    assert "drafter test failed" in out["email"]["subject"]
    assert f"git reset --hard {out['before']}" in out["email"]["text"]


def test_smoke_test_passes_on_this_repo():
    assert updater.smoke_test(config.ROOT) is None
