"""Host-side Podman setup shared by the runner and store provisioning."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from fitting_room.store import StoreError, store_path, wsl_path

BASE_IMAGE = "localhost/fr-base/cpu:1"
BASE_IMAGE_NAMES = frozenset({BASE_IMAGE, BASE_IMAGE.removeprefix("localhost/")})
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CARGO_HOME = "/opt/fr-cargo"
RUSTUP_HOME = "/opt/fr-rustup"
CARGO_TARGET = "/opt/fr-target"
NATIVE_DATA_HOME = "/opt/fr-native-data"
REMOTE_ENV = frozenset({"CONTAINER_HOST", "CONTAINER_CONNECTION", "DOCKER_HOST", "DOCKER_CONTEXT"})


def clean_podman_path() -> str:
    return os.pathsep.join(
        entry
        for entry in os.get_exec_path()
        if entry
        and not Path(entry).resolve().is_relative_to("/mnt")
        and not Path(entry).resolve().is_relative_to("/Docker")
    )


def podman_host_env() -> dict[str, str]:
    path = clean_podman_path()
    compose = os.environ.get("FR_PODMAN_COMPOSE_PROVIDER")
    if not compose:
        # A Nix out-link in the store is a GC root, so garbage collection keeps it:
        #   nix build nixpkgs#docker-compose -o "$FR_STORE/tools/docker-compose"
        pinned = store_path() / "tools" / "docker-compose" / "bin" / "docker-compose"
        if pinned.is_file():
            compose = str(pinned)
    if not compose:
        for entry in path.split(os.pathsep):
            found = shutil.which("docker-compose", path=entry)
            if found and not Path(found).resolve().is_relative_to("/mnt"):
                compose = found
                break
    if not compose:
        raise StoreError(
            "No Linux docker-compose for Podman: run "
            "'nix build nixpkgs#docker-compose -o \"$FR_STORE/tools/docker-compose\"' "
            "or set FR_PODMAN_COMPOSE_PROVIDER"
        )
    executable = wsl_path(Path(compose), "Podman compose provider")
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise StoreError(f"Podman compose provider is not executable: {executable}")
    return {"PATH": path, "PODMAN_COMPOSE_PROVIDER": str(executable)}


def local_podman_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in REMOTE_ENV}


def check_storage(tasks: Path, results: Path, host_env: dict[str, str]) -> dict[str, Path]:
    paths = {
        "FR_STORE": store_path(),
        "tasks": wsl_path(tasks, "tasks"),
        "results": wsl_path(results, "results"),
    }
    try:
        info = subprocess.run(
            ["podman", "info", "--format", "{{.Store.GraphRoot}} {{.Host.Security.Rootless}}"],
            env={**local_podman_env(), **host_env},
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        graph, rootless = info.stdout.strip().rsplit(" ", 1)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise StoreError(f"Could not read rootless Podman storage: {exc}") from exc
    if rootless != "true" or not Path(graph).is_absolute():
        raise StoreError("Benchmarks require local rootless Podman")
    paths["Podman graph root"] = wsl_path(Path(graph), "Podman graph root")
    return paths


def check_task_gpu(uuid: str, host_env: dict[str, str]) -> None:
    """Check that the selected WSL GPU UUID is present before provisioning."""
    try:
        inventory = subprocess.run(
            ["/usr/lib/wsl/lib/nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
            env={**local_podman_env(), **host_env},
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoreError(f"Cannot enumerate WSL GPUs for campaign [gpu] task_gpu: {exc}") from exc
    if uuid.lower() not in {line.strip().lower() for line in inventory.stdout.splitlines()}:
        raise StoreError(f"Campaign [gpu] task_gpu {uuid} is missing from the WSL GPU inventory")
