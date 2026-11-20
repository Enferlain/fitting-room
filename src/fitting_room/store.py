"""Host storage for canonical benchmark inputs."""

from __future__ import annotations

import fcntl
import os
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class StoreError(ValueError):
    """A benchmark store or an input needed to populate it is unusable."""


def component(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", name):
        raise StoreError(f"Invalid store path component: {name!r}")
    return name


def wsl_path(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.is_relative_to("/mnt"):
        raise StoreError(f"{label} must be on the WSL filesystem: {resolved}")
    return resolved


def store_path() -> Path:
    default = Path.home() / ".local/share/fitting-room/store"
    return wsl_path(Path(os.environ.get("FR_STORE") or default), "FR_STORE")


def uv_cache() -> Path:
    default = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "uv"
    return wsl_path(Path(os.environ.get("UV_CACHE_DIR") or default), "uv cache")


def _device(path: Path) -> int:
    while not path.exists():
        path = path.parent
    return path.stat().st_dev


def check_uv_filesystem(store: Path, cache: Path) -> None:
    if _device(store) != _device(cache):
        raise StoreError(f"FR_STORE ({store}) and uv cache ({cache}) must share a filesystem")


@contextmanager
def store_lock(store: Path, *, exclusive: bool) -> Iterator[None]:
    store.mkdir(parents=True, exist_ok=True)
    with (store / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


@contextmanager
def building_entry(path: Path) -> Iterator[None]:
    """Create a recipe-owned entry and clean up a failed build."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    try:
        yield
    except BaseException as original:
        try:
            shutil.rmtree(path)
        except OSError as cleanup:
            if isinstance(original, Exception):
                raise StoreError(
                    f"{original}\nCleanup of {path} also failed: {cleanup}"
                ) from original
            original.add_note(f"Cleanup of {path} also failed: {cleanup}")
        raise
