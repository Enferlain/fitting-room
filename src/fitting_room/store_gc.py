"""Identify obsolete benchmark environments and unreferenced harness versions."""

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
            if config.get("kind", "python") == "python":
                canonical[path.stem] = python_inputs(path.stem, configs).key
            else:
                canonical[path.stem] = native_key(path.stem, config, configs)
        run_configs = sorted(root.runs.glob("*.toml"))
        harness_installs = []
        for path in _entries(store / "harness"):
            marker = path / "harness.json"
            if marker.is_file():
                data = json.loads(marker.read_text())
                if (data.get("harness"), data.get("version")) == (path.parent.name, path.name):
                    harness_installs.append(path)
        if harness_installs and not run_configs:
            raise StoreError(
                f"Found no run configs under {root.runs}; cannot evaluate harness refs"
            )
        runs = [load_run(path.stem, root) for path in run_configs]
        harnesses = {(run.harness, run.harness_version) for run in runs}
        stale = [
            path
            for path in _entries(store / "envs")
            if path.parent.name in canonical
            and path.name != canonical[path.parent.name]
            and re.fullmatch(r"[a-f0-9]{20}", path.name)
            and (path / "env.json").is_file()
        ]
        stale.extend(
            path for path in harness_installs if (path.parent.name, path.name) not in harnesses
        )
        if apply:
            for path in stale:
                shutil.rmtree(path)
        return stale
