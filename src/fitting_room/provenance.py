"""Per-trial provenance sidecar (spec: benchmark-runs, "Results stored with full provenance").

Harbor's result.json records the task path, checksum, timings and agent. The sidecar
`fitting_room.json` adds what Harbor does not know: the resolved run configuration and
content digests of the arm, toolkit and serving profile actually used, plus the task's
own version from task.toml.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from fitting_room import __version__
from fitting_room.config import ConfigRoot, RunConfig

SIDECAR_NAME = "fitting_room.json"
SIDECAR_SCHEMA = 1


def digest_path(path: Path) -> str | None:
    """sha256 over a file, or over every file in a directory (relative path + content)."""
    if not path.exists():
        return None
    h = hashlib.sha256()
    files = (
        [path]
        if path.is_file()
        else sorted(p for p in path.rglob("*") if p.is_file() and p.name != ".gitkeep")
    )
    for f in files:
        rel = f.name if path.is_file() else f.relative_to(path).as_posix()
        h.update(rel.encode() + b"\0" + f.read_bytes() + b"\0")
    return "sha256:" + h.hexdigest()


def task_version(task_dir: Path) -> str | None:
    toml_path = task_dir / "task.toml"
    if not toml_path.is_file():
        return None
    data = tomllib.loads(toml_path.read_text())
    return (data.get("task") or {}).get("version") or (data.get("metadata") or {}).get("version")


def build_sidecar(run: RunConfig, root: ConfigRoot, task_dir: Path, campaign: str) -> dict:
    serving = None
    if run.serving_profile:
        profile = root.serving / f"{run.serving_profile}.yaml"
        serving = {
            "name": run.serving_profile,
            "digest": digest_path(profile),
            "content": profile.read_text() if profile.is_file() else None,
        }
    return {
        "schema": SIDECAR_SCHEMA,
        "fitting_room_version": __version__,
        "campaign": campaign,
        "run": run.model_dump(),
        "arm": {"name": run.arm, "digest": digest_path(root.arms / run.arm)},
        "toolkit": {"name": run.toolkit, "digest": digest_path(root.toolkits / run.toolkit)},
        "serving_profile": serving,
        "task": {"path": str(task_dir), "version": task_version(task_dir)},
    }


def write_sidecars(
    job_dir: Path,
    run: RunConfig,
    root: ConfigRoot,
    campaign: str,
    *,
    podman_options: dict | None = None,
) -> int:
    """Write a sidecar into every trial of a finished Harbor job. Returns the count."""
    n = 0
    for result_path in sorted(job_dir.glob("*/result.json")):
        result = json.loads(result_path.read_text())
        task_path = Path((result.get("task_id") or {}).get("path") or "")
        sidecar = build_sidecar(run, root, task_path, campaign)
        if podman_options is not None:
            from fitting_room.environments.podman import task_repo

            source = task_repo(task_path)
            environment = podman_options["repo_environments"].get(source)
            sidecar["environment"] = environment
            sidecar["harness_store_path"] = podman_options.get("harness_path")
            sidecar["toolkit_store_path"] = podman_options.get("toolkit_path")
        sidecar["trial"] = result.get("trial_name")
        (result_path.parent / SIDECAR_NAME).write_text(json.dumps(sidecar, indent=2) + "\n")
        n += 1
    return n
