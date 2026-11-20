"""Toolkits (design D13; spec: harness-adapters, benchmark-runs).

A toolkit is a run dimension separate from the arm. ``configs/toolkits/<name>/`` holds a
``toolkit.toml`` (``none`` has none: nothing is added). Items are ``cli``, ``mcp``,
``skill`` or ``hook``. Wiring:

- store: pinned tools are provisioned in the benchmark store and mounted read-only;
- ``mcp`` and ``skill`` items: Harbor's agent config (``mcp_servers``, ``skills``), which
  each Harbor agent registers in its harness's own config inside the clean harness home;
- a harness that cannot support an item is refused before any trial starts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from fitting_room.harness_store import SEMVER, provision_in_base
from fitting_room.store import StoreError, building_entry, component, store_lock, wsl_path

KINDS = ("cli", "mcp", "skill", "hook")

#: What each harness can take. cli works everywhere (it is on PATH). MCP and skills go
#: through Harbor's agent config (omp: native mcp.json, see adapters/omp.py). hooks: no
#: harness wired yet, so a toolkit with a hook item is refused everywhere.
HARNESS_SUPPORT: dict[str, set[str]] = {
    "claude-code": {"cli", "mcp", "skill"},
    "codex": {"cli", "mcp", "skill"},
    "opencode": {"cli", "mcp", "skill"},
    "hermes": {"cli", "mcp", "skill"},
    "omp": {"cli", "mcp", "skill"},
}


@dataclass
class Item:
    name: str
    kind: str
    usage: list[str] = field(default_factory=list)
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    path: str | None = None


@dataclass
class Toolkit:
    name: str
    path: Path
    dockerfile_append: str = ""
    store: dict[str, str] = field(default_factory=dict)
    announce: bool = False
    items: list[Item] = field(default_factory=list)

    def store_digest(self) -> str | None:
        if not self.store:
            return None
        pins = json.dumps(
            {"recipe": TOOLKIT_RECIPE, "pins": self.store}, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(pins.encode()).hexdigest()

    def mcp_servers(self) -> list[dict]:
        return [
            {"name": i.name, "transport": i.transport, "command": i.command, "args": i.args}
            for i in self.items
            if i.kind == "mcp"
        ]

    def skill_dirs(self) -> list[str]:
        return [str((self.path / i.path).resolve()) for i in self.items if i.kind == "skill"]


def load_toolkit(toolkits_dir: Path, name: str) -> Toolkit:
    path = toolkits_dir / name
    cfg_path = path / "toolkit.toml"
    if not cfg_path.exists():
        return Toolkit(name=name, path=path)  # e.g. "none": nothing added
    cfg = tomllib.loads(cfg_path.read_text())
    items = []
    for raw in cfg.get("items", []):
        item = Item(**raw)
        if item.kind not in KINDS:
            raise ValueError(f"toolkit {name}: item {item.name} has unknown kind {item.kind!r}")
        if item.kind == "mcp" and not item.command:
            raise ValueError(f"toolkit {name}: MCP item {item.name} needs a command")
        if item.kind == "skill" and not (item.path and (path / item.path / "SKILL.md").exists()):
            raise ValueError(f"toolkit {name}: skill item {item.name} has no SKILL.md")
        items.append(item)
    store = cfg.get("store", {})
    if (
        not isinstance(store, dict)
        or set(store) - {"bd", "openspec"}
        or any(not isinstance(pin, str) or not re.fullmatch(SEMVER, pin) for pin in store.values())
    ):
        raise ValueError(f"toolkit {name}: [store] accepts pinned bd and openspec versions")
    if store and cfg.get("dockerfile_append", "").strip():
        raise ValueError(f"toolkit {name}: [store] cannot be combined with dockerfile_append")
    return Toolkit(
        name=name,
        path=path,
        dockerfile_append=cfg.get("dockerfile_append", ""),
        store=store,
        announce=bool(cfg.get("announce", False)),
        items=items,
    )


def unsupported(harness: str, toolkit: Toolkit) -> list[str]:
    """Items the harness cannot take (empty for oracle/nop, which ignore toolkits)."""
    if harness not in HARNESS_SUPPORT:
        return []
    ok = HARNESS_SUPPORT[harness]
    return [f"{i.name} ({i.kind})" for i in toolkit.items if i.kind not in ok]


#: Toolkit installer recipe, part of the store digest: bump when the install script
#: changes what ends up in the store, so old installs are not reused (GC removes them).
TOOLKIT_RECIPE = 1


def ensure_toolkit(toolkit: Toolkit, store: Path) -> Path:
    digest = toolkit.store_digest()
    if digest is None:
        raise StoreError(f"Toolkit '{toolkit.name}' has no store pins")
    name = component(toolkit.name)
    path = store / "toolkits" / name / digest
    if wsl_path(path, "toolkit install") != path:
        raise StoreError(f"Toolkit install must use its store path: {path}")
    manifest = path / "toolkit.digest"
    commands = ["mkdir -p bin"]
    if version := toolkit.store.get("bd"):
        url = shlex.quote(f"https://github.com/gastownhall/beads/releases/download/v{version}")
        commands.append(
            """
case "$(uname -m)" in x86_64) arch=amd64;; aarch64) arch=arm64;; *) exit 1;; esac
"""
            f'archive="beads_{version}_linux_$arch.tar.gz"\n'
            f"base={url}"
            + """
tmp=$(mktemp -d)
download() {
    curl -fsSL --connect-timeout 15 --retry 3 --speed-limit 1024 --speed-time 60 "$1" -o "$2"
}
download "$base/$archive" "$tmp/$archive"
download "$base/checksums.txt" "$tmp/checksums.txt"
(cd "$tmp"; awk -v name="$archive" '$2 == name' checksums.txt | sha256sum -c -)
tar -xzf "$tmp/$archive" -C "$tmp"
install -m 755 "$(find "$tmp" -type f -name bd -print -quit)" bin/bd
"""
        )
    if version := toolkit.store.get("openspec"):
        package = shlex.quote(f"@fission-ai/openspec@{version}")
        commands.append(f'npm install -g --prefix "$PWD" --no-audit --no-fund {package}')
    with (
        store_lock(store, exclusive=False),
        store_lock(store / "locks" / "toolkits" / name / digest, exclusive=True),
    ):
        if manifest.is_file():
            if manifest.read_text().strip() == digest and all(
                (path / "bin" / tool).is_file() and os.access(path / "bin" / tool, os.X_OK)
                for tool in toolkit.store
            ):
                return path
            # A completed entry may be mounted by a concurrent campaign.
            raise StoreError(f"Invalid toolkit install at {path}; remove it with campaigns stopped")
        with building_entry(path):
            provision_in_base(path, "\n".join(commands))
            for tool, pin in toolkit.store.items():
                version = provision_in_base(path, f"./bin/{tool} --version", verify=True)
                if not re.search(rf"(?<![.0-9a-z-]){re.escape(pin)}(?![.0-9a-z-])", version):
                    raise StoreError(f"{tool}: expected {pin}, got {version!r}")
            staged = manifest.with_suffix(".tmp")
            staged.write_text(digest + "\n")
            staged.replace(manifest)
    return path


def stage_tasks(task_dirs: list[Path], toolkit: Toolkit, staging: Path) -> list[Path]:
    """Hardlinked copies of the tasks with the toolkit's image layer appended."""
    if toolkit.store:
        raise StoreError(f"Toolkit '{toolkit.name}' requires a Podman task")
    if not toolkit.dockerfile_append.strip():
        return list(task_dirs)
    out = []
    for src in task_dirs:
        dest = staging / toolkit.name / src.name
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, copy_function=_link_or_copy, symlinks=True)
        dockerfile = dest / "environment" / "Dockerfile"
        text = dockerfile.read_text()
        dockerfile.unlink()  # break the hardlink before editing
        dockerfile.write_text(
            text.rstrip("\n")
            + f"\n\n# fr toolkit: {toolkit.name}\n"
            + toolkit.dockerfile_append.strip("\n")
            + "\n"
        )
        out.append(dest)
    return out


def _link_or_copy(src: str, dst: str) -> None:
    try:
        Path(dst).hardlink_to(src)
    except OSError:
        shutil.copy2(src, dst)
