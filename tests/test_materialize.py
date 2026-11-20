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


@pytest.mark.parametrize("prebuilt", [False, True])
def test_snapshot_is_start_commit_without_secrets_or_history(tmp_path, repo, monkeypatch, prebuilt):
    r, first = repo
    monkeypatch.setenv("FR_REPOS_DIR", str(r.parent))
    task = make_task(tmp_path, first[:8])
    if prebuilt:
        (task / "environment" / "Dockerfile").unlink()
        with (task / "task.toml").open("a") as cfg:
            cfg.write('[environment]\ndocker_image = "fr-base/cpu:1"\n')
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


def test_links_inside_repo_kept_outside_stripped(tmp_path, monkeypatch):
    r = tmp_path / "repos" / "demo"
    (r / "skills").mkdir(parents=True)
    (r / "plugin" / "x").mkdir(parents=True)
    git(r, "init", "-q")
    (r / "skills" / "s.md").write_text("s")
    (r / "plugin" / "x" / "skills").symlink_to("../../skills")
    (r / "out").symlink_to("../../etc")
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "one")
    monkeypatch.setenv("FR_REPOS_DIR", str(r.parent))
    m = materialize(make_task(tmp_path, git(r, "rev-parse", "HEAD")))
    dest = tmp_path / "task" / "environment" / "repo"
    assert (dest / "plugin" / "x" / "skills").is_symlink()
    assert m.stripped == ["out"]


def test_repo_excludes_and_task_includes(tmp_path, monkeypatch):
    from fitting_room.tasks import materialize as mz

    r = tmp_path / "repos" / "demo"
    (r / "stage5" / "artifacts" / "keep").mkdir(parents=True)
    (r / "src").mkdir()
    git(r, "init", "-q")
    (r / "src" / "a.py").write_text("code")
    (r / "stage5" / "artifacts" / "run1").mkdir()
    (r / "stage5" / "artifacts" / "run1" / "x.json").write_text("{}")
    (r / "stage5" / "artifacts" / "top.json").write_text("{}")
    (r / "stage5" / "artifacts" / "keep" / "y.json").write_text("{}")
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "one")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "demo.toml").write_text('exclude = ["stage*/artifacts/*/**"]\n')
    monkeypatch.setattr(mz, "REPO_CONFIGS", cfg)
    monkeypatch.setenv("FR_REPOS_DIR", str(r.parent))
    task = make_task(tmp_path, git(r, "rev-parse", "HEAD"))
    with (task / "task.toml").open("a") as fh:
        fh.write('snapshot_include = ["stage5/artifacts/keep/**"]\n')
    m = materialize(task)
    dest = task / "environment" / "repo"
    assert (dest / "src" / "a.py").exists()
    assert not (dest / "stage5" / "artifacts" / "run1" / "x.json").exists()
    assert (dest / "stage5" / "artifacts" / "top.json").exists()  # files directly under stay
    assert (dest / "stage5" / "artifacts" / "keep" / "y.json").exists()
    assert m.excluded == 1
