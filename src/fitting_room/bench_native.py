"""Warm Debian-compatible Rust inputs for native benchmark repos."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
from pathlib import Path

from fitting_room.bench_env import benchmark_config, ensure_python, managed_python, python_inputs
from fitting_room.podman_host import (
    BASE_IMAGE,
    CARGO_HOME,
    CARGO_TARGET,
    NATIVE_DATA_HOME,
    RUSTUP_HOME,
    SYSTEM_PATH,
    clean_podman_path,
    local_podman_env,
)
from fitting_room.store import StoreError, building_entry, store_lock
from fitting_room.tasks.materialize import REPO_CONFIGS, _matches, repo_excludes, repo_path

RUSTUP_URL = "https://sh.rustup.rs"
#: 2: the repo's own workspace crates are removed from warmed targets (they were built
#: from the canonical commit, newer than most task snapshots, and must not leak into them).
RECIPE = 2
#: Shell helper run after warming: drop every workspace member's artifacts so only
#: dependencies (crates.io, vendored path deps outside the workspace) stay warm.
CLEAN_OWN = r"""
clean_own() {
    cargo metadata --no-deps --offline --locked --format-version 1 --manifest-path "$1" |
        jq -r '.packages[].name' | sort -u | while read -r package; do
            cargo clean --offline -p "$package" --manifest-path "$1"
            cargo clean --offline -p "$package" --manifest-path "$1" --release
        done
}
"""


def native_key(repo: str, config: dict, configs: Path) -> str:
    kind, commit, rust = config.get("kind"), config.get("commit"), config.get("rust")
    if kind not in {"rust", "pytortch", "python+rust"}:
        raise StoreError(f"{repo}: invalid [benchmark] kind {kind!r}")
    if not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise StoreError(f"{repo}: [benchmark] commit must be a full Git commit ID")
    if not isinstance(rust, str) or not re.fullmatch(r"\d+\.\d+\.\d+", rust):
        raise StoreError(f"{repo}: [benchmark] rust must pin a toolchain version")
    python_key = {
        "pytortch": lambda: python_inputs("sd-scripts", configs).key,
        "python+rust": lambda: python_inputs(repo, configs).key,
    }.get(kind, lambda: None)()
    inputs = [RECIPE, kind, commit, rust, python_key]
    if kind == "python+rust":
        inputs.append(rust_manifests(repo, config))
    if kind == "pytortch":
        inputs.append(NATIVE_DATA_HOME)
    return hashlib.sha256(json.dumps(inputs).encode()).hexdigest()[:20]


def rust_manifests(repo: str, config: dict) -> list[str]:
    """Cargo manifests warmed for a Python repo that also carries Rust crates."""
    manifests = config.get("rust_manifests")
    if (
        not isinstance(manifests, list)
        or not manifests
        or not all(
            isinstance(m, str)
            and m.endswith("Cargo.toml")
            and not m.startswith(("/", ".."))
            and ".." not in Path(m).parts
            for m in manifests
        )
    ):
        raise StoreError(
            f"{repo}: [benchmark] rust_manifests must list repo-relative Cargo.toml paths"
        )
    return list(manifests)


def _archive(repo: str, commit: str, dest: Path, configs: Path) -> None:
    excludes = repo_excludes(repo, configs)
    source = repo_path(repo)
    with (
        tempfile.TemporaryFile() as stderr,
        subprocess.Popen(
            ["git", "-C", str(source), "archive", commit],
            stdout=subprocess.PIPE,
            stderr=stderr,
        ) as git,
    ):
        archive_error = None
        try:
            with tarfile.open(fileobj=git.stdout, mode="r|") as tar:
                tar.extractall(
                    dest,
                    (m for m in tar if not _matches(m.name, excludes, m.isdir())),
                    filter="data",
                )
        except tarfile.TarError as exc:
            archive_error = exc
            git.stdout.close()
        if git.wait() or archive_error is not None:
            stderr.seek(0)
            detail = stderr.read().decode(errors="replace").strip() or str(archive_error)
            raise StoreError(
                f"Cannot extract canonical source {repo}@{commit}: {detail}"
            ) from archive_error


def _warm(repo: str, config: dict, dest: Path, configs: Path, python: Path | None) -> None:
    workdir = f"/work/{repo}"
    rust = config["rust"]
    script = (
        'curl --proto "=https" --tlsv1.2 -fsSL --retry 3 --retry-all-errors '
        f"--connect-timeout 20 --max-time 120 {RUSTUP_URL} -o /tmp/rustup.sh\n"
        f"sh /tmp/rustup.sh -y --no-modify-path --profile minimal --default-toolchain {rust}"
        " --component clippy,rustfmt\n"
    )
    mounts = [f"{dest / 'cargo'}:{CARGO_HOME}", f"{dest / 'rustup'}:{RUSTUP_HOME}"]
    env = {
        "PATH": f"{CARGO_HOME}/bin:{SYSTEM_PATH}",
        "CARGO_HOME": CARGO_HOME,
        "RUSTUP_HOME": RUSTUP_HOME,
        "RUSTUP_TOOLCHAIN": rust,
    }
    if config["kind"] == "rust":
        env["CARGO_TARGET_DIR"] = CARGO_TARGET
        mounts.append(f"{dest / 'target'}:{CARGO_TARGET}")
        script += (
            "cargo fetch --locked\ncargo test --workspace --locked --offline --no-run\n"
            + CLEAN_OWN
            + "clean_own Cargo.toml"
        )
    elif config["kind"] == "python+rust":
        # One shared target dir for every manifest, as trials set CARGO_TARGET_DIR.
        env["CARGO_TARGET_DIR"] = CARGO_TARGET
        mounts.append(f"{dest / 'target'}:{CARGO_TARGET}")
        for manifest in rust_manifests(repo, config):
            path = shlex.quote(manifest)
            script += (
                f"\ncargo fetch --locked --manifest-path {path}"
                f"\ncargo test --locked --offline --no-run --manifest-path {path}"
            )
        script += (
            "\n"
            + CLEAN_OWN
            + "\n".join(f"clean_own {shlex.quote(m)}" for m in rust_manifests(repo, config))
        )
    else:
        assert python is not None
        tree = python.parent.parent
        mounts.append(f"{tree}:{tree}:ro")
        env["PATH"] = f"{python.parent}:{env['PATH']}"
        # The LLVM bundler also installs an SDK under XDG_DATA_HOME. Its
        # absolute path is captured in the Cargo build fingerprint.
        env["XDG_DATA_HOME"] = NATIVE_DATA_HOME
        (dest / "tracel").mkdir()
        mounts.append(f"{dest / 'tracel'}:{NATIVE_DATA_HOME}/tracel")
        for source, target in (
            ("target", "cubecl_torch/native/target"),
            ("bridge-target", "cubecl_torch/native/bridge/target"),
        ):
            mounts.append(f"{dest / source}:{workdir}/{target}")
        script += (
            "git -c init.defaultBranch=main init -q\n"
            "git add -A && git -c user.name=benchmark -c user.email=benchmark@local"
            " commit -qm benchmark\n"
            "cubecl_torch/native/build.sh\n"
            + CLEAN_OWN
            + "clean_own cubecl_torch/native/Cargo.toml\n"
            "clean_own cubecl_torch/native/bridge/Cargo.toml"
        )
    for name in ("cargo", "rustup", "target", "bridge-target"):
        (dest / name).mkdir()
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        warm = Path(tmp)
        _archive(repo, config["commit"], warm, configs)
        mounts.append(f"{warm}:{workdir}")
        command = [
            "podman",
            "run",
            "--rm",
            "--pull=never",
            "--userns=keep-id",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--workdir",
            workdir,
        ]
        for mount in mounts:
            command.extend(["--volume", mount])
        for key, value in env.items():
            command.extend(["--env", f"{key}={value}"])
        command.extend([BASE_IMAGE, "sh", "-ec", script])
        if subprocess.call(command, env={**local_podman_env(), "PATH": clean_podman_path()}):
            raise StoreError(f"Could not warm the Debian Rust toolchain and target for {repo}")


def ensure_environment(
    repo: str, store: Path, configs: Path = REPO_CONFIGS, *, offline: bool = False
) -> dict:
    config = benchmark_config(repo, configs)
    if config.get("kind", "python") == "python":
        return ensure_python(python_inputs(repo, configs), store, offline=offline)
    key = native_key(repo, config, configs)
    dest = store / "envs" / repo / key
    record = dest / "env.json"
    python = {
        "pytortch": lambda: python_inputs("sd-scripts", configs),
        "python+rust": lambda: python_inputs(repo, configs),
    }.get(config["kind"], lambda: None)()
    with store_lock(store, exclusive=False):
        with store_lock(store / "locks" / repo / key, exclusive=True):
            if record.is_file():
                data = json.loads(record.read_text())
            else:
                data = _ensure_native(
                    repo,
                    store,
                    config,
                    configs,
                    dest,
                    key,
                    python.python if python else None,
                    offline=offline,
                )
        if python is None:
            return data
        env = ensure_python(python, store, offline=offline)
        return env | data | {"python_key": env["key"]}


def _ensure_native(
    repo: str,
    store: Path,
    config: dict,
    configs: Path,
    dest: Path,
    key: str,
    version: str | None,
    *,
    offline: bool,
) -> dict:
    if offline:
        raise StoreError(f"No warmed Rust environment for {repo}; run fr env ensure {repo}")
    python = managed_python(version, store, offline=False) if version else None
    with building_entry(dest):
        _warm(repo, config, dest, configs, python)
        data = {
            "repo": repo,
            "key": key,
            "commit": config["commit"],
            "kind": config["kind"],
            "rust": config["rust"],
            "native": str(dest),
        }
        pending = dest / "env.tmp"
        pending.write_text(json.dumps(data, indent=2) + "\n")
        pending.rename(dest / "env.json")
    return data
