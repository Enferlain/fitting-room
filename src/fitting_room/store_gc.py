"""Identify obsolete benchmark environments and unused store installs."""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from pathlib import Path

from fitting_room.bench_env import python_inputs
from fitting_room.bench_native import native_key
from fitting_room.config import ConfigRoot, load_run
from fitting_room.store import StoreError, store_lock
from fitting_room.toolkits import load_toolkit


def _entries(directory: Path) -> list[Path]:
    if directory.is_symlink():
        return []
    return sorted(
        path
        for path in directory.glob("*/*")
        if path.is_dir() and not (path.is_symlink() or path.parent.is_symlink())
    )


def collect_store(store: Path, root: ConfigRoot, *, apply: bool = False) -> list[Path]:
    """Collect obsolete managed entries. Preview unless apply is explicit."""
    if not store.exists():
        return []
    configs = root.path / "repos"
    with store_lock(store, exclusive=apply):
        canonical = {}
        for path in configs.glob("*.toml"):
            config = tomllib.loads(path.read_text()).get("benchmark")
            if config is None:
                continue
            kind = config.get("kind", "python")
            keys = set()
            if kind in ("python", "python+rust"):
                keys.add(python_inputs(path.stem, configs).key)
            if kind != "python":
                keys.add(native_key(path.stem, config, configs))
            canonical[path.stem] = keys
        run_configs = sorted(root.runs.glob("*.toml"))
        harness_installs = []
        for path in _entries(store / "harness"):
            marker = path / "harness.json"
            if marker.is_file():
                data = json.loads(marker.read_text())
                if (data.get("harness"), data.get("version")) == (path.parent.name, path.name):
                    harness_installs.append(path)
        toolkit_installs = [
            path
            for path in _entries(store / "toolkits")
            if re.fullmatch(r"[a-f0-9]{64}", path.name)
            and (path / "toolkit.digest").is_file()
            and (path / "toolkit.digest").read_text().strip() == path.name
        ]
        if (harness_installs or toolkit_installs) and not run_configs:
            raise StoreError(
                f"Found no run configs under {root.runs}; cannot evaluate harness and toolkit refs"
            )
        runs = [load_run(path.stem, root) for path in run_configs]
        harnesses = {(run.harness, run.harness_version) for run in runs}
        stale = [
            path
            for path in _entries(store / "envs")
            if path.parent.name in canonical
            and path.name not in canonical[path.parent.name]
            and re.fullmatch(r"[a-f0-9]{20}", path.name)
            and (path / "env.json").is_file()
        ]
        stale.extend(
            path for path in harness_installs if (path.parent.name, path.name) not in harnesses
        )
        toolkit_digests = {
            name: load_toolkit(root.toolkits, name).store_digest()
            for name in {run.toolkit for run in runs}
        }
        stale.extend(
            path for path in toolkit_installs if path.name != toolkit_digests.get(path.parent.name)
        )
        if apply:
            # Leave the empty per-entry lock files in place so a lock's inode
            # stays stable across collection and subsequent provisioning.
            for path in stale:
                shutil.rmtree(path)
        return stale
