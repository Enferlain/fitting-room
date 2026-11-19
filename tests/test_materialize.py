import json
import subprocess

import pytest

from fitting_room.tasks.materialize import MaterializeError, materialize


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True,
                          text=True).stdout.strip()  # fmt: skip


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repos" / "demo"
    r.mkdir(parents=True)
    git(r, "init", "-q")
    (r / "a.py").write_text("v1\n")
    (r / ".env").write_text("SECRET=1\n")
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "one")
    first = git(r, "rev-parse", "HEAD")
    (r / "a.py").write_text("v2 answer\n")
    (r / "b.py").write_text("later\n")
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "two")
    return r, first


def make_task(tmp_path, commit):
    task = tmp_path / "task"
    (task / "environment").mkdir(parents=True)
    (task / "environment" / "Dockerfile").write_text("FROM scratch\n")
    (task / "task.toml").write_text(
        f'[task]\nname = "fr/demo-x"\n[metadata]\nrepo = "demo"\nstart_commit = "{commit}"\n'
    )
    return task


def test_snapshot_is_start_commit_without_secrets_or_history(tmp_path, repo, monkeypatch):
    r, first = repo
    monkeypatch.setenv("FR_REPOS_DIR", str(r.parent))
    task = make_task(tmp_path, first[:8])
    (task / "environment" / "repo").mkdir()
    (task / "environment" / "repo" / "stale.txt").write_text("old")
    m = materialize(task)
    dest = task / "environment" / "repo"
    assert m.commit == first
    assert (dest / "a.py").read_text() == "v1\n"
    assert not (dest / "b.py").exists() and not (dest / "stale.txt").exists()
    assert not (dest / ".env").exists() and m.stripped == [".env"]
    assert not (dest / ".git").exists()
    rec = json.loads((task / "environment" / ".materialized.json").read_text())
    assert rec["commit"] == first


def test_missing_metadata_refused(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("FR_REPOS_DIR", str(repo[0].parent))
    task = make_task(tmp_path, "x")
    (task / "task.toml").write_text('[task]\nname = "fr/demo-x"\n[metadata]\nrepo = "demo"\n')
    with pytest.raises(MaterializeError, match="start_commit"):
        materialize(task)
