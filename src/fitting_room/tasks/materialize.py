"""`fr task materialize`: put the repo snapshot into a task (spec: task-authoring; design D8).

`environment/repo/` is `git archive <start_commit>` of the local repo named in the task's
`[metadata]` (`repo`, `start_commit`). It is gitignored and rebuilt on demand. The task
Dockerfile re-inits it as one fresh commit, so the image has no later history, refs,
remotes or hooks. A small record of what was materialized sits next to it
(`environment/.materialized.json`), outside the `COPY repo/` path so it never reaches
the image.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPOS_DIR_ENV = "FR_REPOS_DIR"
DEFAULT_REPOS_DIR = Path("~/Projects")
RECORD = ".materialized.json"
#: Never copied into a snapshot, whatever the commit holds.
STRIP_NAMES = {".env", ".envrc", ".netrc", ".npmrc", ".pypirc"}


class MaterializeError(Exception):
    pass


@dataclass
class Materialized:
    repo: str
    commit: str
    files: int
    stripped: list[str]
    submodules: bool
    dest: Path


def task_source(task_dir: Path) -> tuple[str, str]:
    meta = tomllib.loads((task_dir / "task.toml").read_text()).get("metadata", {})
    repo, commit = meta.get("repo"), meta.get("start_commit")
    if not repo or not commit:
        raise MaterializeError(f"{task_dir}/task.toml needs [metadata] repo and start_commit")
    return repo, commit


def repo_path(repo: str) -> Path:
    base = Path(os.environ.get(REPOS_DIR_ENV) or DEFAULT_REPOS_DIR).expanduser()
    path = base / repo
    if not (path / ".git").exists():
        raise MaterializeError(f"no git repo at {path} (set {REPOS_DIR_ENV} to override)")
    return path


def _git(path: Path, *args: str, binary: bool = False) -> bytes | str:
    out = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=not binary)
    if out.returncode != 0:
        err = out.stderr if not binary else out.stderr.decode(errors="replace")
        raise MaterializeError(f"git {' '.join(args)} failed: {err.strip()}")
    return out.stdout


def _inside_repo(m: tarfile.TarInfo) -> bool:
    """True if a link's target stays inside the archive root."""
    link = PurePosixPath(m.linkname)
    if link.is_absolute():
        return False
    base = PurePosixPath(m.name).parent if m.issym() else PurePosixPath()
    depth = 0
    for part in (*base.parts, *link.parts):
        depth += -1 if part == ".." else (0 if part == "." else 1)
        if depth < 0:
            return False
    return True


def materialize(task_dir: Path, *, repo: str | None = None, commit: str | None = None) -> Materialized:
    """Replace ``<task>/environment/repo/`` with the repo at the task's start commit."""
    if repo is None or commit is None:
        repo, commit = task_source(task_dir)
    src = repo_path(repo)
    full = str(_git(src, "rev-parse", "--verify", f"{commit}^{{commit}}")).strip()
    env = task_dir / "environment"
    if not (env / "Dockerfile").exists():
        raise MaterializeError(f"{env}/Dockerfile missing: not a task directory")
    dest = env / "repo"
    if dest.exists():
        shutil.rmtree(dest)  # always a generated, gitignored snapshot
    dest.mkdir(parents=True)
    archive = _git(src, "archive", "--format=tar", full, binary=True)
    stripped: list[str] = []
    files = 0
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = []
        for m in tar.getmembers():
            if Path(m.name).name in STRIP_NAMES:
                stripped.append(m.name)
                continue
            if (m.issym() or m.islnk()) and not _inside_repo(m):
                stripped.append(m.name)  # links out of the repo would leak host paths
                continue
            members.append(m)
            files += m.isfile()
        tar.extractall(dest, members=members, filter="data")
    submodules = (dest / ".gitmodules").exists()
    record = {"repo": repo, "commit": full, "files": files, "stripped": stripped,
              "submodules_not_included": submodules}  # fmt: skip
    (env / RECORD).write_text(json.dumps(record, indent=1) + "\n")
    return Materialized(repo, full, files, stripped, submodules, dest)
