import json
import subprocess
from pathlib import Path

import pytest
import yaml

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
    (r / ".beads").mkdir()
    (r / ".beads/config.yaml").write_text(
        "sync.remote: https://example.invalid/dotted\n"
        "sync: {remote: https://example.invalid/nested, enabled: true}\n"
        "dolt.shared-server: true\n"
        "dolt: {server-port: 3308, auto-commit: batch}\n"
        "issue-prefix: demo\n"
    )
    (r / ".beads/metadata.json").write_text('{"dolt_mode":"server"}\n')
    (r / ".beads/issues.jsonl").write_text('{"id":"demo-1"}\n')
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
    task.mkdir(parents=True)
    (task / "task.toml").write_text(
        f'[task]\nname = "fr/demo-x"\n[metadata]\nrepo = "demo"\nstart_commit = "{commit}"\n'
        '[environment]\ndocker_image = "fr-base/cpu:1"\n'
    )
    return task


def test_snapshot_is_start_commit_without_secrets_or_history(tmp_path, repo, monkeypatch):
    r, first = repo
    monkeypatch.setenv("FR_REPOS_DIR", str(r.parent))
    task = make_task(tmp_path, first[:8])
    (task / "environment" / "repo").mkdir(parents=True)
    (task / "environment" / "repo" / "stale.txt").write_text("old")
    m = materialize(task)
    dest = task / "environment" / "repo"
    assert m.commit == first
    assert (dest / "a.py").read_text() == "v1\n"
    assert not (dest / "b.py").exists() and not (dest / "stale.txt").exists()
    assert not (dest / ".env").exists()
    assert set(m.stripped) == {".env", ".beads/metadata.json"}
    assert not (dest / ".beads/metadata.json").exists()
    assert (dest / ".beads/issues.jsonl").is_file()
    assert git(dest, "rev-list", "--all", "--count") == "1"
    assert git(dest, "branch", "--show-current") == "main"
    assert git(dest, "log", "--format=%s") == "init"
    assert git(dest, "log", "--format=%ae") == "benchmark@example.invalid"
    assert git(dest, "reflog", "--all") == git(dest, "remote") == git(dest, "tag") == ""
    assert git(dest, "status", "--porcelain") == ""
    assert not (dest / ".git/hooks").exists()
    assert yaml.safe_load((dest / ".beads/config.yaml").read_text()) == {
        "sync": {"enabled": True},
        "dolt": {"auto-commit": "batch"},
        "issue-prefix": "demo",
    }
    commit = git(dest, "rev-parse", "HEAD")
    materialize(task)
    assert git(dest, "rev-parse", "HEAD") == commit
    rec = json.loads((task / "environment" / ".materialized.json").read_text())
    assert rec["commit"] == first
    assert rec["snapshot_commit"] == commit


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
    config = task / "task.toml"
    config.write_text(
        config.read_text().replace(
            "[environment]", 'snapshot_include = ["stage5/artifacts/keep/**"]\n[environment]'
        )
    )
    m = materialize(task)
    dest = task / "environment" / "repo"
    assert (dest / "src" / "a.py").exists()
    assert not (dest / "stage5" / "artifacts" / "run1" / "x.json").exists()
    assert (dest / "stage5" / "artifacts" / "top.json").exists()  # files directly under stay
    assert (dest / "stage5" / "artifacts" / "keep" / "y.json").exists()
    assert m.excluded == 1


def test_directory_probe_fails_when_solution_string_is_present(tmp_path, repo, monkeypatch):
    r, first = repo
    monkeypatch.setenv("FR_REPOS_DIR", str(r.parent))
    task = make_task(tmp_path, first)
    probe = (
        Path(__file__).resolve().parents[1]
        / ".agents/skills/evals-from-sessions/assets/leak-probe.sh"
    )
    strings = tmp_path / "solution-strings"
    strings.write_text("unique private reference answer\n")
    assert subprocess.run(["bash", probe, task, strings], check=False).returncode == 2
    snapshot = materialize(task).dest
    assert subprocess.run(["bash", probe, task, strings], check=False).returncode == 0
    (snapshot / ".leaked").write_text(strings.read_text())
    assert subprocess.run(["bash", probe, task, strings], check=False).returncode == 1


def test_invalid_snapshot_keeps_previous_materialization(tmp_path, repo, monkeypatch):
    r, first = repo
    monkeypatch.setenv("FR_REPOS_DIR", str(r.parent))
    task = make_task(tmp_path, first)
    dest = materialize(task).dest
    original = git(dest, "rev-parse", "HEAD")
    (r / ".beads/config.yaml").write_text("dolt: [\n")
    git(r, "add", ".beads/config.yaml")
    git(r, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "bad config")
    with pytest.raises(MaterializeError, match="Invalid Beads config"):
        materialize(task, repo="demo", commit="HEAD")
    assert git(dest, "rev-parse", "HEAD") == original
    record = json.loads((dest.parent / ".materialized.json").read_text())
    assert record["snapshot_commit"] == original
