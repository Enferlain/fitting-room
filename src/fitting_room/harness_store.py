"""Provision pinned harnesses in the same Debian base used by trials."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from fitting_room.podman_host import BASE_IMAGE, clean_podman_path, local_podman_env
from fitting_room.store import StoreError, building_entry, store_lock, wsl_path

BINARIES = {
    "claude-code": "claude",
    "codex": "codex",
    "opencode": "opencode",
    "omp": "omp",
    "hermes": "hermes",
}
NPM_PACKAGES = {
    "claude-code": "@anthropic-ai/claude-code",
    "codex": "@openai/codex",
    "opencode": "@opencode/cli",
}
#: Installer recipe per harness. Bump when an install script changes what ends up in the
#: store (e.g. opencode 2: only the linked platform build is kept). An entry built with
#: another recipe is never reused; `fr store gc --apply` removes it.
RECIPES = {"claude-code": 1, "codex": 1, "opencode": 2, "omp": 1, "hermes": 1}
SEMVER = r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
HERMES_SHA = r"[0-9a-f]{40}"


def provision_in_base(path: Path, script: str, *, verify: bool = False) -> str:
    """Install at the final absolute path, or verify it offline and read-only."""
    command = [
        "podman",
        "run",
        "--rm",
        "--pull=never",
        "--timeout",
        "30" if verify else "900",
        "--userns=keep-id",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--env",
        "HOME=/tmp/fr-home",
        "--volume",
        f"{path}:{path}" + (":ro" if verify else ""),
        "--workdir",
        str(path),
    ]
    if verify:
        command.extend(["--network", "none"])
    command.extend([BASE_IMAGE, "bash", "-euo", "pipefail", "-c", 'mkdir -p "$HOME";\n' + script])
    result = subprocess.run(
        command,
        env={**local_podman_env(), "PATH": clean_podman_path()},
        stdout=subprocess.PIPE if verify else None,
        text=True,
    )
    if result.returncode != 0:
        raise StoreError(f"Provisioning {path} failed (Podman exit {result.returncode})")
    return (result.stdout or "").strip()


def version_matches(name: str, version: str, output: str) -> bool:
    """Compare the CLI's reported version, including Hermes's checkout revision."""
    if name == "hermes":
        return bool(
            re.search(r"(?m)^Hermes Agent v[^ ]+ \(\d{4}\.\d+\.\d+\)", output)
            and output.strip().splitlines()[-1] == version
        )
    pattern = {
        "codex": rf"codex-cli ({SEMVER})",
        "claude-code": rf"({SEMVER}) \(Claude Code\)",
        "opencode": rf"(?:opencode\s+v?|v)?({SEMVER})",
        "omp": rf"(?:omp/)?({SEMVER})",
    }[name]
    return any(
        (match := re.fullmatch(pattern, line.strip())) and match[1] == version
        for line in output.splitlines()
    )


def version_command(name: str, path: Path) -> str:
    command = f"{shlex.quote(str(path / 'bin' / BINARIES[name]))} --version"
    if name == "hermes":
        command = (
            f"HERMES_HOME=/tmp/fr-hermes-version {command} && "
            f"git -C {shlex.quote(str(path / 'source'))} rev-parse HEAD"
        )
    return command


def _install_script(name: str, version: str) -> str:
    if name in NPM_PACKAGES:
        package = shlex.quote(f"{NPM_PACKAGES[name]}@{version}")
        script = f'npm install -g --prefix "$PWD" --no-audit --no-fund {package}'
        if name == "opencode":
            # npm installs every linux-x64 build (glibc/musl, baseline/regular, ~250 MB
            # each); the postinstall hardlinks one to bin/opencode.exe. Keep only that one.
            script += """
cli=lib/node_modules/@opencode/cli
inode=$(stat -c %i "$cli/bin/opencode.exe")
for variant in "$cli"/node_modules/@opencode/cli-*; do
    [ -n "$(find "$variant" -type f -inum "$inode" -print -quit)" ] || rm -rf "$variant"
done
"""
        return script
    if name == "omp":
        url = f"https://github.com/can1357/oh-my-pi/releases/download/v{version}"
        return f"""
case "$(uname -m)" in x86_64) arch=x64;; aarch64) arch=arm64;; *) exit 1;; esac
download() {{
    curl -fsSL --connect-timeout 15 --retry 3 --speed-limit 1024 --speed-time 60 "$1" -o "$2"
}}
asset="omp-linux-$arch"
mkdir bin
cd bin
download "{url}/SHA256SUMS.txt" "$HOME/omp-sha256"
download "{url}/$asset" "$asset"
awk -v name="$asset" '$2 == name' "$HOME/omp-sha256" | sha256sum -c -
mv "$asset" omp
chmod 755 omp
"""
    # Use the pinned upstream lock and its curated "all" extra, as the
    # upstream installer does for Python. Skip its browser bootstrap.
    return f"""
git init -q source
git -C source fetch --depth=1 https://github.com/NousResearch/hermes-agent.git {version}
git -C source checkout -q --detach FETCH_HEAD
test "$(git -C source rev-parse HEAD)" = {version}
export UV_PYTHON_INSTALL_DIR="$PWD/python" UV_CACHE_DIR="$HOME/uv"
export UV_PROJECT_ENVIRONMENT="$PWD/venv"
uv sync --project source --locked --no-dev --extra all --python 3.11
mkdir bin
ln -s ../venv/bin/hermes bin/hermes
"""


def ensure_harness(name: str, version: str, store: Path) -> Path:
    if name not in BINARIES:
        raise StoreError(f"Unknown stored harness: {name}")
    if not re.fullmatch(HERMES_SHA if name == "hermes" else SEMVER, version):
        raise StoreError(f"Pin {name} by {'full commit SHA' if name == 'hermes' else 'version'}")
    path = store / "harness" / name / version
    if wsl_path(path, "harness install") != path:
        raise StoreError(f"Harness install must use its store path: {path}")
    manifest = path / "harness.json"
    expected = {"harness": name, "version": version, "recipe": RECIPES[name]}
    executable = path / "bin" / BINARIES[name]
    with (
        store_lock(store, exclusive=False),
        store_lock(store / "locks" / "harness" / name / version, exclusive=True),
    ):
        try:
            installed = json.loads(manifest.read_text())
        except FileNotFoundError:
            pass
        except json.JSONDecodeError as exc:
            raise StoreError(
                f"Invalid harness manifest in {path}; remove the entry with campaigns stopped"
            ) from exc
        else:
            if installed == expected and executable.is_file() and os.access(executable, os.X_OK):
                return path
            if installed.get("recipe") != expected["recipe"]:
                raise StoreError(
                    f"{path} was built with installer recipe {installed.get('recipe')}, current is "
                    f"{expected['recipe']}; remove it with campaigns stopped (fr store gc --apply)"
                )
            # A completed entry may be mounted by a concurrent campaign.
            raise StoreError(f"Invalid harness install at {path}; remove it with campaigns stopped")
        with building_entry(path):
            provision_in_base(path, _install_script(name, version))
            output = provision_in_base(path, version_command(name, path), verify=True)
            if not version_matches(name, version, output):
                raise StoreError(f"{name}: expected {version}, got {output!r}")
            staged = manifest.with_suffix(".tmp")
            staged.write_text(json.dumps(expected, indent=2) + "\n")
            staged.replace(manifest)
    return path
