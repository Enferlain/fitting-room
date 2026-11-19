"""Toolkits (design D13; spec: harness-adapters, benchmark-runs).

A toolkit is a run dimension separate from the arm. ``configs/toolkits/<name>/`` holds a
``toolkit.toml`` (``none`` has none: nothing is added). Items are ``cli``, ``mcp``,
``skill`` or ``hook``. Wiring:

- image: ``dockerfile_append`` goes onto a staged, hardlinked copy of each task, so
  task directories are never edited;
- ``mcp`` and ``skill`` items: Harbor's agent config (``mcp_servers``, ``skills``), which
  each Harbor agent registers in its harness's own config inside the clean harness home;
- a harness that cannot support an item is refused before any trial starts.
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

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
    announce: bool = False
    items: list[Item] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.items and not self.dockerfile_append.strip()

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
    return Toolkit(
        name=name,
        path=path,
        dockerfile_append=cfg.get("dockerfile_append", ""),
        announce=bool(cfg.get("announce", False)),
        items=items,
    )


def unsupported(harness: str, toolkit: Toolkit) -> list[str]:
    """Items the harness cannot take (empty for oracle/nop, which ignore toolkits)."""
    if harness not in HARNESS_SUPPORT:
        return []
    ok = HARNESS_SUPPORT[harness]
    return [f"{i.name} ({i.kind})" for i in toolkit.items if i.kind not in ok]


def stage_tasks(task_dirs: list[Path], toolkit: Toolkit, staging: Path) -> list[Path]:
    """Hardlinked copies of the tasks with the toolkit's image layer appended."""
    if toolkit.empty or not toolkit.dockerfile_append.strip():
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
