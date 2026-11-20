"""Harbor's rootless Podman backend with benchmark store inputs."""

from __future__ import annotations

import json
import re
import shlex
import tomllib
from pathlib import Path

from harbor.environments.podman import PodmanEnvironment, PodmanOptions
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths
from pydantic import Field

from fitting_room.podman_host import (
    BASE_IMAGE,
    BASE_IMAGE_NAMES,
    CARGO_HOME,
    CARGO_TARGET,
    NATIVE_DATA_HOME,
    RUSTUP_HOME,
    SYSTEM_PATH,
)
from fitting_room.store import StoreError, component

IMPORT_PATH = "fitting_room.environments.podman:FrPodmanEnvironment"
SNAPSHOT = "/opt/fr-snapshot"


class FrPodmanOptions(PodmanOptions):
    repo_environments: dict[str, dict] = Field(default_factory=dict)
    task_gpu: str | None = None
    harness_path: Path | None = None
    toolkit_path: Path | None = None


def task_repo(task: Path) -> str | None:
    meta = tomllib.loads((task / "task.toml").read_text()).get("metadata", {})
    repo = meta.get("repo")
    return component(repo) if repo is not None else None


def validate_gpu(gpus: int, task_gpu: str | None) -> None:
    uuid = r"GPU-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
    if gpus and (gpus != 1 or not re.fullmatch(uuid, task_gpu or "", re.IGNORECASE)):
        raise StoreError("WSL GPU tasks require gpus = 1 and a campaign [gpu] task_gpu UUID")


def trial_service(
    snapshot: Path | None, repo: str | None, benchmark: dict, options: FrPodmanOptions, gpus: int
) -> tuple[dict, list[str]]:
    mounts = []
    variables = {"PATH": SYSTEM_PATH}
    setup = []
    service = {"init": True}

    def bind(source: Path, target: str | None = None) -> None:
        mounts.append(
            {
                "type": "bind",
                "source": str(source),
                "target": target or str(source),
                "read_only": True,
                "bind": {"create_host_path": False},
            }
        )

    def prepend_path(path: Path) -> None:
        variables["PATH"] = f"{path}:{variables['PATH']}"

    if snapshot is not None:
        bind(snapshot, SNAPSHOT)
        service["working_dir"] = f"/work/{repo}"
        setup.append(f"cp -a --no-preserve=ownership {SNAPSHOT}/. .")
    venv_path = benchmark.get("venv")
    if venv_path:
        venv = Path(venv_path)
        python = Path(benchmark["python"])
        bind(venv)
        # The whole interpreter store, not just the resolved install: uv links the venv
        # through its minor-version alias (cpython-3.14-...), which must resolve too.
        bind(python.parent.parent.parent)
        variables.update(
            VIRTUAL_ENV=str(venv),
            UV_PROJECT_ENVIRONMENT=str(venv),
            UV_NO_SYNC="1",
            UV_PYTHON_DOWNLOADS="never",
            UV_PYTHON=str(python),
        )
        prepend_path(venv / "bin")
    if native := benchmark.get("native"):
        bind(Path(native), "/opt/fr-native-seed")
        variables.update(
            CARGO_HOME=CARGO_HOME,
            RUSTUP_HOME=RUSTUP_HOME,
            RUSTUP_TOOLCHAIN=benchmark["rust"],
            CARGO_NET_OFFLINE="true",
        )
        prepend_path(Path(CARGO_HOME) / "bin")
        bind(Path(native) / "rustup", RUSTUP_HOME)
        setup.append(f"mkdir -p {CARGO_HOME}")
        setup.append(f"cp -a --reflink=auto /opt/fr-native-seed/cargo/. {CARGO_HOME}/")
        if benchmark["kind"] == "pytortch":
            if not venv_path:
                raise StoreError("pytortch requires the canonical sd-scripts venv")
            bind(Path(native) / "tracel", f"{NATIVE_DATA_HOME}/tracel")
            variables["XDG_DATA_HOME"] = NATIVE_DATA_HOME
            stage_python = shlex.quote(str(venv / "bin/python"))
            setup.extend(
                [
                    f"uv venv --no-python-downloads --python {stage_python} stage0/.venv",
                    "stage0/.venv/bin/python stage0/isolate_python.py "
                    f"{shlex.quote(str(venv))}/lib/python*/site-packages",
                    "mkdir -p cubecl_torch/native/target cubecl_torch/native/bridge/target",
                    "cp -a --reflink=auto /opt/fr-native-seed/target/. cubecl_torch/native/target/",
                    "cp -a --reflink=auto /opt/fr-native-seed/bridge-target/. "
                    "cubecl_torch/native/bridge/target/",
                    "cubecl_torch/native/build.sh",
                ]
            )
        else:
            variables["CARGO_TARGET_DIR"] = CARGO_TARGET
            setup.extend(
                [
                    f"mkdir -p {CARGO_TARGET}",
                    f"cp -a --reflink=auto /opt/fr-native-seed/target/. {CARGO_TARGET}/",
                ]
            )
    for install in (options.harness_path, options.toolkit_path):
        if install is not None:
            bind(install)
            prepend_path(install / "bin")
    validate_gpu(gpus, options.task_gpu)
    if gpus:
        # The Podman compatibility API treats the short bind form differently
        # on WSL's /usr/lib/wsl mount (the long bind form fails inside crun).
        mounts.append("/usr/lib/wsl:/usr/lib/wsl:ro")
        service["devices"] = ["/dev/dxg"]
        prepend_path(Path("/usr/lib/wsl/lib"))
        variables.update(
            CUDA_VISIBLE_DEVICES=options.task_gpu,
            LD_LIBRARY_PATH="/usr/lib/wsl/lib",
        )
    service.update(volumes=mounts, environment=variables, command=["sleep", "infinity"])
    return service, setup


class FrPodmanEnvironment(PodmanEnvironment):
    options_model = FrPodmanOptions

    def __init__(
        self,
        environment_dir: Path,
        environment_name: str,
        session_id: str,
        trial_paths: TrialPaths,
        task_env_config: EnvironmentConfig,
        *,
        repo_environments: dict[str, dict] | None = None,
        task_gpu: str | None = None,
        harness_path: str | None = None,
        toolkit_path: str | None = None,
        **kwargs,
    ) -> None:
        if task_env_config.docker_image not in BASE_IMAGE_NAMES:
            raise StoreError(f"Fitting-room Podman tasks must use {BASE_IMAGE}")
        task_env_config = task_env_config.model_copy(update={"docker_image": BASE_IMAGE})
        options = FrPodmanOptions(
            repo_environments=repo_environments or {},
            task_gpu=task_gpu,
            harness_path=harness_path,
            toolkit_path=toolkit_path,
        )
        if (environment_dir / "Dockerfile").exists():
            raise StoreError("Remove environment/Dockerfile for a prebuilt Podman task")
        repo = task_repo(environment_dir.parent)
        snapshot = None
        if repo is not None:
            snapshot = (environment_dir / "repo").resolve()
            if not snapshot.is_dir() or repo not in options.repo_environments:
                raise StoreError(f"Missing snapshot or canonical environment for {repo}")
            task_env_config = task_env_config.model_copy(update={"workdir": f"/work/{repo}"})
        super().__init__(
            environment_dir,
            environment_name,
            session_id,
            trial_paths,
            task_env_config,
            **(kwargs | {"enable_environment_dir_upload": repo is None}),
        )
        service, self._setup = trial_service(
            snapshot,
            repo,
            options.repo_environments.get(repo, {}),
            options,
            self._effective_gpus,
        )
        overlay = trial_paths.trial_dir / f"{component(session_id)}.compose.json"
        overlay.write_text(json.dumps({"services": {"main": service}}, indent=2) + "\n")
        self.extra_docker_compose_paths.append(overlay)

    @property
    def capabilities(self):
        return super().capabilities.model_copy(update={"gpus": True})

    async def start(self, force_build: bool) -> None:
        if force_build:
            raise StoreError("Fitting-room Podman tasks use a prebuilt base image")
        await super().start(force_build=False)
        if self._setup:
            result = await self.exec("set -eu; " + "; ".join(self._setup))
            self.logger.debug("Trial setup output:\n%s%s", result.stdout or "", result.stderr or "")
            if result.return_code:
                command = shlex.join(self._setup)
                raise RuntimeError(f"Trial setup failed ({command}): {result.stderr}")
