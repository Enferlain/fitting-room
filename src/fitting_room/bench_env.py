"""Provision the single environment selected by each repo's benchmark config."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from fitting_room.store import (
    StoreError,
    building_entry,
    check_uv_filesystem,
    component,
    store_lock,
    uv_cache,
)
from fitting_room.tasks.materialize import (
    REPO_CONFIGS,
    MaterializeError,
    _git,
    repo_path,
    task_source,
)

RECIPE = 1


@dataclass(frozen=True)
class PythonInputs:
    repo: str
    commit: str
    python: str
    sync_args: tuple[str, ...]
    pyproject: str
    lock: str

    @property
    def key(self) -> str:
        payload = [RECIPE, self.python, self.sync_args, self.pyproject, self.lock]
        return hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:20]


def benchmark_config(repo: str, configs: Path = REPO_CONFIGS) -> dict:
    config = configs / f"{component(repo)}.toml"
    benchmark = tomllib.loads(config.read_text()).get("benchmark") if config.is_file() else None
    if not isinstance(benchmark, dict) or not benchmark:
        raise StoreError(f"No canonical benchmark environment configured in {config}")
    return benchmark


def python_inputs(repo: str, configs: Path = REPO_CONFIGS) -> PythonInputs:
    config = benchmark_config(repo, configs)
    commit, python = config.get("commit"), config.get("python")
    if not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise StoreError(f"{repo}: [benchmark] commit must be a full Git commit ID")
    if not isinstance(python, str) or not re.fullmatch(r"3\.\d+\.\d+t?", python):
        raise StoreError(f"{repo}: [benchmark] python must pin the interpreter patch version")
    src = repo_path(repo)
    return PythonInputs(
        repo,
        commit,
        python,
        tuple(config.get("sync_args", [])),
        str(_git(src, "show", f"{commit}:pyproject.toml")),
        str(_git(src, "show", f"{commit}:uv.lock")),
    )


def _command(args: list[str], env: dict[str, str]) -> str:
    out = subprocess.run(args, env=env, capture_output=True, text=True)
    if out.returncode:
        raise StoreError(f"{' '.join(args[:3])} failed:\n{out.stderr.strip()}")
    return out.stdout.strip()


def _python(version: str, store: Path, env: dict[str, str], offline: bool) -> Path:
    find = ["uv", "python", "find", "--managed-python", "--no-project", version]
    try:
        return Path(_command(find, env)).resolve()
    except StoreError:
        pass
    host_env = dict(env)
    host_env.pop("UV_PYTHON_INSTALL_DIR")
    try:
        cached = Path(_command(find, host_env)).resolve()
    except StoreError:
        if offline:
            raise
    else:
        tree = cached.parent.parent
        dest = store / "python" / tree.name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=dest.parent) as temp:
                copy = Path(temp) / tree.name
                shutil.copytree(tree, copy, symlinks=True)
                copy.rename(dest)
        return Path(_command(find, env)).resolve()
    _command(["uv", "python", "install", "--no-bin", version], env)
    return Path(_command(find, env)).resolve()


def managed_python(version: str, store: Path, *, offline: bool) -> Path:
    env = {k: v for k, v in os.environ.items() if not k.startswith("UV_")}
    env["UV_PYTHON_INSTALL_DIR"] = str(store / "python")
    if offline:
        env["UV_OFFLINE"] = "1"
    with store_lock(store / "locks" / "python", exclusive=True):
        return _python(version, store, env, offline)


def _expose_project(venv: Path, repo: str, pyproject: str, env: dict[str, str]) -> None:
    python = venv / "bin/python"
    site = Path(
        _command([str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], env)
    )
    worktree = f"/work/{repo}"
    (site / "fitting-room-project.pth").write_text(f"{worktree}/src\n{worktree}\n")
    project = tomllib.loads(pyproject).get("project", {})
    for name, entry in project.get("scripts", {}).items():
        module, function = entry.split(":", 1)
        script = venv / "bin" / component(name)
        payload = (
            "import sys\nfrom importlib import import_module\n"
            "sys.argv.pop(0)\n"
            f"fn = import_module({module!r})\n"
            f"for name in {function.split('.')!r}:\n    fn = getattr(fn, name)\n"
            "sys.exit(fn())\n"
        )
        if script.exists() or script.is_symlink():
            raise StoreError(f"{repo}: project script {name!r} conflicts with a dependency")
        with script.open("x") as stream:
            stream.write(
                f'#!/bin/sh\nexec {shlex.quote(str(python))} -c {shlex.quote(payload)} "$0" "$@"\n'
            )
        script.chmod(0o755)


def ensure_python(inputs: PythonInputs, store: Path, *, offline: bool = False) -> dict:
    cache = uv_cache()
    check_uv_filesystem(store, cache)
    directory = store / "envs" / inputs.repo / inputs.key
    record = directory / "env.json"
    venv = directory / "venv"
    with (
        store_lock(store, exclusive=False),
        store_lock(store / "locks" / inputs.repo / inputs.key, exclusive=True),
    ):
        if record.is_file():
            data = json.loads(record.read_text())
            if (venv / "bin/python").exists() and Path(data["python"]).is_file():
                return data
            raise StoreError(f"Canonical environment is incomplete: {directory}")
        env = {k: v for k, v in os.environ.items() if not k.startswith("UV_")}
        env.update(
            UV_CACHE_DIR=str(cache),
            UV_LINK_MODE="hardlink",
            UV_PYTHON_INSTALL_DIR=str(store / "python"),
            UV_PROJECT_ENVIRONMENT=str(venv),
        )
        if offline:
            env["UV_OFFLINE"] = "1"
        for key in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX"):
            env.pop(key, None)
        python = managed_python(inputs.python, store, offline=offline)
        with building_entry(directory):
            with tempfile.TemporaryDirectory(dir=store) as tmp:
                project = Path(tmp)
                (project / "pyproject.toml").write_text(inputs.pyproject)
                (project / "uv.lock").write_text(inputs.lock)
                _command(
                    [
                        "uv",
                        "sync",
                        "--project",
                        str(project),
                        "--frozen",
                        "--no-install-project",
                        "--python",
                        str(python),
                        *inputs.sync_args,
                    ],
                    env,
                )
            _expose_project(venv, inputs.repo, inputs.pyproject, env)
            data = {
                "repo": inputs.repo,
                "key": inputs.key,
                "commit": inputs.commit,
                "venv": str(venv),
                "python": str(python),
                "interpreter": _command([str(python), "--version"], env),
                "free_threaded": inputs.python.endswith("t"),
                "lock_sha256": hashlib.sha256(inputs.lock.encode()).hexdigest(),
            }
            (directory / "uv.lock").write_text(inputs.lock)
            pending = record.with_suffix(".tmp")
            pending.write_text(json.dumps(data, indent=2) + "\n")
            pending.rename(record)
        return data


def _versions(lock: str) -> dict[str, set[str]]:
    versions: dict[str, set[str]] = {}
    for package in tomllib.loads(lock).get("package", []):
        versions.setdefault(package["name"], set()).add(package.get("version", "(unversioned)"))
    return versions


def check_task(task: Path, configs: Path = REPO_CONFIGS) -> dict:
    repo, commit = task_source(task)
    config = benchmark_config(repo, configs)
    if config.get("kind", "python") != "python":
        raise StoreError(f"{repo}: fr env check compares uv locks for Python benchmark configs")
    inputs = python_inputs(repo, configs)
    src = repo_path(repo)
    if not re.fullmatch(r"[a-fA-F0-9]{7,40}", commit):
        raise StoreError(f"{task}: expected a Git commit ID")
    _git(src, "rev-parse", "--verify", f"{commit}^{{commit}}")
    try:
        lock = str(_git(src, "show", f"{commit}:uv.lock"))
    except MaterializeError:
        return {"repo": repo, "key": inputs.key, "historical_lock": None}
    canonical, historical = _versions(inputs.lock), _versions(lock)
    return {
        "repo": repo,
        "key": inputs.key,
        "historical_lock": "identical" if lock == inputs.lock else "different",
        "canonical_python": inputs.python,
        "historical_requires_python": tomllib.loads(lock).get("requires-python"),
        "packages": {
            name: {
                "historical": sorted(historical.get(name, ())),
                "canonical": sorted(canonical.get(name, ())),
            }
            for name in sorted(canonical.keys() | historical.keys())
            if historical.get(name) != canonical.get(name)
        },
    }
