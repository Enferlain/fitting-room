"""Start and stop benchmark serving profiles (spec: local-model-serving; design D11).

A serving profile is a standalone llama-swap config in ``configs/serving/<name>.yaml``.
On this host llama-swap and llama-server are Windows binaries, so the profile is
launched through PowerShell, which returns the real Windows PID. ``down`` stops exactly
that process tree. Name-based kills are never used, so an everyday llama-swap that
happens to be running is never touched. With WSL mirrored networking, the profile
listening on 127.0.0.1 is reachable from WSL and, via host.docker.internal, from
Harbor sandboxes.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LISTEN = "127.0.0.1:18080"
LLAMA_SWAP_EXE = "llama-swap.exe"


@dataclass
class ServeState:
    profile: str
    windows_pid: int
    listen: str
    config_path: str

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2) + "\n"


def _state_file(work_dir: Path, profile: str) -> Path:
    return work_dir / "serving" / f"{profile}.json"


def _ps(command: str) -> str:
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(f"powershell failed ({out.returncode}): {out.stderr.strip()[:500]}")
    return out.stdout.strip()


def _windows_path(path: Path) -> str:
    return subprocess.run(
        ["wslpath", "-w", str(path.resolve())], capture_output=True, text=True, check=True
    ).stdout.strip()


def endpoint_up(listen: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://{listen}/v1/models", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def serve_up(
    profile: str, config_root: Path, work_dir: Path, listen: str = DEFAULT_LISTEN
) -> ServeState:
    cfg = config_root / "serving" / f"{profile}.yaml"
    if not cfg.is_file():
        raise FileNotFoundError(f"no serving profile {cfg}")
    state_path = _state_file(work_dir, profile)
    if state_path.exists():
        raise RuntimeError(
            f"profile '{profile}' already up (state in {state_path}); run down first"
        )
    if endpoint_up(listen):
        raise RuntimeError(f"something is already serving on {listen}")
    win_cfg = _windows_path(cfg)
    (work_dir / "serving").mkdir(parents=True, exist_ok=True)
    # No output redirection: redirected handles keep PowerShell attached to the child.
    # llama-swap keeps its own logs, readable at http://<listen>/logs.
    try:
        pid = _ps(
            f"(Start-Process -FilePath '{LLAMA_SWAP_EXE}' "
            f"-ArgumentList '-config','\"{win_cfg}\"','-listen','{listen}' "
            f"-WindowStyle Hidden -PassThru).Id"
        )
    except (RuntimeError, subprocess.TimeoutExpired):
        pid = find_windows_pid(win_cfg)
        if pid is None:
            raise
    state = ServeState(profile, int(pid), listen, str(cfg))
    state_path.write_text(state.to_json())
    for _ in range(60):
        if endpoint_up(listen):
            return state
        time.sleep(1)
    raise RuntimeError(
        f"llama-swap (pid {pid}) did not answer on {listen}; see http://{listen}/logs"
    )


def find_windows_pid(win_cfg: str) -> int | None:
    """PID of the llama-swap whose command line names this exact config file."""
    out = _ps(
        "Get-CimInstance Win32_Process -Filter \"Name='llama-swap.exe'\" | "
        'ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }'
    )
    for line in out.splitlines():
        pid, _, cmdline = line.partition("\t")
        if win_cfg.lower() in cmdline.lower():
            return int(pid)
    return None


def adopt(profile: str, config_root: Path, work_dir: Path, listen: str = DEFAULT_LISTEN):
    """Record state for a profile that is running but has no state file."""
    cfg = config_root / "serving" / f"{profile}.yaml"
    pid = find_windows_pid(_windows_path(cfg))
    if pid is None:
        return None
    state = ServeState(profile, pid, listen, str(cfg))
    _state_file(work_dir, profile).parent.mkdir(parents=True, exist_ok=True)
    _state_file(work_dir, profile).write_text(state.to_json())
    return state


def serve_down(profile: str, work_dir: Path) -> bool:
    """Stop the profile's llama-swap process tree. Returns False if it was not up."""
    state_path = _state_file(work_dir, profile)
    if not state_path.exists():
        return False
    state = ServeState(**json.loads(state_path.read_text()))
    subprocess.run(
        ["taskkill.exe", "/PID", str(state.windows_pid), "/T", "/F"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    state_path.unlink()
    return True
