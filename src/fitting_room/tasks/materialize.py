"""`fr task materialize`: put the repo snapshot into a task (spec: task-authoring; design D8).

`environment/repo/` is `git archive <start_commit>` of the local repo named in the task's
`[metadata]` (`repo`, `start_commit`), initialized as one fresh commit on the host.
The snapshot is gitignored. Its materialization record lives beside it
(`environment/.materialized.json`).

Per-repo excludes (generated evidence that floods tools) come from
``configs/repos/<repo>.toml`` (``exclude`` = glob patterns on repo-relative paths); a
task can bring paths back with ``[metadata] snapshot_include``.
"""

from __future__ import annotations

import fcntl
import io
import json
import os
import subprocess
import tarfile
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

import yaml

from fitting_room.podman_host import BASE_IMAGE_NAMES
from fitting_room.store import StoreError, component

REPOS_DIR_ENV = "FR_REPOS_DIR"
DEFAULT_REPOS_DIR = Path("~/Projects")
RECORD = ".materialized.json"
#: Never copied into a snapshot, whatever the commit holds.
STRIP_NAMES = {".env", ".envrc", ".netrc", ".npmrc", ".pypirc"}
DOLT_CONNECTION = {
    "shared-server",
    "server-host",
    "server-port",
    "server-user",
    "server-socket",
    "server-tls",
}


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
    excluded: int = 0


REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs" / "repos"


def repo_excludes(repo: str, configs: Path | None = None) -> list[str]:
    path = (configs or REPO_CONFIGS) / f"{repo}.toml"
    return list(tomllib.loads(path.read_text()).get("exclude", [])) if path.exists() else []


def _matches(name: str, patterns: list[str], is_dir: bool = False) -> bool:
    """Glob match on a repo-relative path; a directory also matches as "<dir>/"."""
    return any(fnmatch(name, p) or (is_dir and fnmatch(name + "/", p)) for p in patterns)


def task_source(task_dir: Path) -> tuple[str, str]:
    meta = tomllib.loads((task_dir / "task.toml").read_text()).get("metadata", {})
    repo, commit = meta.get("repo"), meta.get("start_commit")
    if not repo or not commit:
        raise MaterializeError(f"{task_dir}/task.toml needs [metadata] repo and start_commit")
    return repo, commit


def repo_path(repo: str) -> Path:
    base = Path(os.environ.get(REPOS_DIR_ENV) or DEFAULT_REPOS_DIR).expanduser()
    try:
        path = base / component(repo)
    except StoreError as exc:
        raise MaterializeError(str(exc)) from exc
    if not (path / ".git").exists():
        raise MaterializeError(f"no git repo at {path} (set {REPOS_DIR_ENV} to override)")
    return path


def _git(path: Path, *args: str, binary: bool = False) -> bytes | str:
    # Discard caller Git settings, object directories, templates, and identities.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_ATTR_NOSYSTEM="1",
        GIT_AUTHOR_NAME="benchmark",
        GIT_AUTHOR_EMAIL="benchmark@example.invalid",
        GIT_COMMITTER_NAME="benchmark",
        GIT_COMMITTER_EMAIL="benchmark@example.invalid",
        GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
        GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
    )
    command = ["git", "-C", str(path), "-c", "core.attributesFile=/dev/null", *args]
    out = subprocess.run(command, capture_output=True, text=not binary, env=env)
    if out.returncode != 0:
        err = out.stderr if not binary else out.stderr.decode(errors="replace")
        raise MaterializeError(f"git {' '.join(args)} failed: {err.strip()}")
    return out.stdout


def _initialize_snapshot(snapshot: Path) -> None:
    beads = snapshot / ".beads/config.yaml"
    if beads.is_symlink() and beads.is_file():
        # Read the seed from the snapshot, and write its sanitized copy at this path.
        contents = beads.read_text()
        beads.unlink()
        beads.write_text(contents)
    if beads.is_file():
        try:
            config = yaml.safe_load(beads.read_text())
        except yaml.YAMLError as exc:
            raise MaterializeError(f"Invalid Beads config: {exc}") from exc
        if isinstance(config, dict):
            changed = False
            for section, keys in (("sync", {"remote"}), ("dolt", DOLT_CONNECTION)):
                nested = config.get(section)
                for key in sorted(keys):
                    dotted = f"{section}.{key}"
                    if dotted in config:
                        del config[dotted]
                        changed = True
                    if isinstance(nested, dict) and key in nested:
                        del nested[key]
                        changed = True
            if changed:
                beads.write_text(yaml.safe_dump(config, sort_keys=False))
    _git(snapshot, "init", "-q", "--initial-branch=main", "--template=")
    _git(snapshot, "config", "gc.auto", "0")
    _git(snapshot, "add", "-f", "-A")
    _git(snapshot, "-c", "core.logAllRefUpdates=false", "commit", "-qm", "init", "--allow-empty")


@contextmanager
def snapshot_lock(environment: Path, *, exclusive: bool) -> Iterator[None]:
    """Coordinate snapshot publication and the trial's copy without a lock file."""
    fd = os.open(environment, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        os.close(fd)


def _publish_snapshot(env: Path, staging: Path) -> None:
    with snapshot_lock(env, exclusive=True):
        dest = env / "repo"
        backup = staging / "previous"
        if dest.exists() or dest.is_symlink():
            dest.rename(backup)
        try:
            (staging / "repo").rename(dest)
            try:
                (staging / RECORD).replace(env / RECORD)
            except OSError:
                dest.rename(staging / "repo")
                raise
        except OSError:
            if backup.exists() or backup.is_symlink():
                backup.rename(dest)
            raise


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


def materialize(
    task_dir: Path, *, repo: str | None = None, commit: str | None = None
) -> Materialized:
    """Replace ``<task>/environment/repo/`` with the repo at the task's start commit."""
    if repo is None or commit is None:
        repo, commit = task_source(task_dir)
    env = task_dir / "environment"
    task_config = task_dir / "task.toml"
    config = tomllib.loads(task_config.read_text()) if task_config.is_file() else {}
    image = config.get("environment", {}).get("docker_image")
    if not isinstance(image, str) or image not in BASE_IMAGE_NAMES:
        raise MaterializeError(f"{task_dir} must use the prebuilt Podman base image")
    if any((env / name).exists() for name in ("Dockerfile", "docker-compose.yaml")):
        raise MaterializeError(f"{task_dir} has a legacy environment recipe")
    src = repo_path(repo)
    full = str(_git(src, "rev-parse", "--verify", f"{commit}^{{commit}}")).strip()
    archive = _git(src, "archive", "--format=tar", full, binary=True)
    excludes = repo_excludes(repo)
    includes = list(config.get("metadata", {}).get("snapshot_include", []))
    excluded = 0
    stripped: list[str] = []
    files = 0
    env.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".materialize-", dir=env) as tmp:
        staging = Path(tmp)
        snapshot = staging / "repo"
        snapshot.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            members = []
            for member in tar.getmembers():
                if _matches(member.name, excludes, member.isdir()) and not _matches(
                    member.name, includes, member.isdir()
                ):
                    excluded += member.isfile()
                    continue
                path = PurePosixPath(member.name)
                if (
                    path.name in STRIP_NAMES
                    or path == PurePosixPath(".beads/metadata.json")
                    or path.is_relative_to(".beads/dolt")
                    or ((member.issym() or member.islnk()) and not _inside_repo(member))
                ):
                    stripped.append(member.name)
                    continue
                members.append(member)
                files += member.isfile()
            tar.extractall(snapshot, members=members, filter="data")
        submodules = (snapshot / ".gitmodules").exists()
        _initialize_snapshot(snapshot)
        record = {
            "repo": repo,
            "commit": full,
            "snapshot_commit": str(_git(snapshot, "rev-parse", "HEAD")).strip(),
            "files": files,
            "stripped": stripped,
            "excluded_patterns": excludes,
            "excluded_files": excluded,
            "included_back": includes,
            "submodules_not_included": submodules,
        }
        (staging / RECORD).write_text(json.dumps(record, indent=1) + "\n")
        _publish_snapshot(env, staging)
    return Materialized(repo, full, files, stripped, submodules, env / "repo", excluded)
