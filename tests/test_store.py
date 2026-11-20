import json
import subprocess

import pytest
from typer.testing import CliRunner

from fitting_room.bench_env import check_task, python_inputs
from fitting_room.cli import app
from fitting_room.config import ConfigRoot
from fitting_room.store import StoreError, check_uv_filesystem, store_path
from fitting_room.store_gc import collect_store


@pytest.fixture
def benchmark(tmp_path, monkeypatch):
    repo = tmp_path / "sources" / "example"
    repo.mkdir(parents=True)
    config = tmp_path / "configs" / "repos"
    config.mkdir(parents=True)
    monkeypatch.setenv("FR_REPOS_DIR", str(repo.parent))

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    git("init", "-q")
    (repo / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "1"\n')

    def commit(version):
        (repo / "uv.lock").write_text(
            f'requires-python = ">=3.12"\n[[package]]\nname = "p"\nversion = "{version}"\n'
        )
        git("add", ".")
        git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", version)
        return git("rev-parse", "HEAD")

    historical = commit("1")
    canonical = commit("2")
    (config / "example.toml").write_text(
        f'[benchmark]\ncommit = "{canonical}"\npython = "3.14.5t"\n'
    )
    return config, historical, canonical


def test_historical_lock_and_old_env_selector_are_diagnostic_only(tmp_path, benchmark):
    configs, history, canonical = benchmark
    task = tmp_path / "task"
    task.mkdir()
    store = tmp_path / "store"
    task_toml = task / "task.toml"
    task_toml.write_text(
        f'[metadata]\nrepo = "example"\nstart_commit = "{history}"\nenv = "lock"\n'
    )
    result = check_task(task, configs)
    assert result["historical_lock"] == "different"
    assert result["packages"] == {"p": {"historical": ["1"], "canonical": ["2"]}}
    assert result["key"] == python_inputs("example", configs).key
    task_toml.write_text(f'[metadata]\nrepo = "example"\nstart_commit = "{canonical}"\n')
    identical = check_task(task, configs)
    assert identical["historical_lock"] == "identical" and identical["key"] == result["key"]
    assert not store.exists()


def test_store_rejects_windows_paths_and_symlinks(tmp_path, monkeypatch):
    shortcut = tmp_path / "shortcut"
    shortcut.symlink_to("/mnt/c/benchmark")
    monkeypatch.setenv("FR_STORE", str(shortcut))
    with pytest.raises(StoreError, match="WSL filesystem"):
        store_path()
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 2
    assert "/mnt/c/benchmark" in result.output


def test_store_and_uv_cache_must_share_filesystem(tmp_path, monkeypatch):
    def device(path):
        return 1 if path.name == "store" else 2

    monkeypatch.setattr("fitting_room.store._device", device)
    with pytest.raises(StoreError, match="share a filesystem"):
        check_uv_filesystem(tmp_path / "store", tmp_path / "cache")


def test_gc_only_applies_to_stale_managed_entries(tmp_path, benchmark):
    configs, _, _ = benchmark
    root = ConfigRoot(configs.parent)
    root.runs.mkdir()
    (root.arms / "stock").mkdir(parents=True)
    (root.toolkits / "none").mkdir(parents=True)
    (root.runs / "run.toml").write_text(
        'harness = "omp"\nharness_version = "1"\nmodel = "zai/model"\neffort = "high"\n'
    )
    store = tmp_path / "store"
    active = store / "envs/example" / python_inputs("example", configs).key
    old = store / "envs/example" / ("0" * 20)
    referenced = store / "harness/omp/1"
    old_pin = store / "harness/omp/2"
    foreign = store / "envs/other" / ("1" * 20)
    for path in (active, old, referenced, old_pin, foreign):
        path.mkdir(parents=True)
        (path / "env.json").write_text(json.dumps({"key": path.name}))
    for path in (referenced, old_pin):
        (path / "harness.json").write_text(json.dumps({"harness": "omp", "version": path.name}))
    unmanaged = store / "harness/omp/3"
    unmanaged.mkdir()
    with pytest.raises(StoreError, match="Found no run configs"):
        collect_store(store, ConfigRoot(tmp_path / "wrong-configs"), apply=True)
    assert collect_store(store, root) == [old, old_pin]
    assert old.exists() and old_pin.exists()
    assert collect_store(store, root, apply=True) == [old, old_pin]
    assert all(path.exists() for path in (active, referenced, foreign, unmanaged))
    assert all(not path.exists() for path in (old, old_pin))


def test_failed_store_cleanup_keeps_the_provisioning_error(tmp_path, monkeypatch):
    from fitting_room.store import building_entry

    def cannot_clean(path):
        raise PermissionError(f"cannot delete {path.name}")

    monkeypatch.setattr("fitting_room.store.shutil.rmtree", cannot_clean)
    with pytest.raises(StoreError, match=r"uv build failed\nCleanup .*also failed: cannot delete"):
        with building_entry(tmp_path / "entry"):
            raise StoreError("uv build failed")


def test_native_archive_reports_the_missing_git_commit(tmp_path, benchmark):
    from fitting_room.bench_native import _archive

    configs, _, _ = benchmark
    missing = "0" * 40
    with pytest.raises(StoreError, match=rf"example@{missing}: .+{missing}"):
        _archive("example", missing, tmp_path / "archive", configs)
