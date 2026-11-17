"""Run configurations and campaigns (spec: benchmark-runs; design D4).

A *run configuration* fixes one harness (pinned), one model, one arm, one toolkit, a
reasoning effort and, for local models, one serving profile. A *campaign* combines run
configurations with a task selection and a repeat count.

Both are TOML files under ``configs/``. Loading validates everything up front and
reports every problem at once, so nothing starts with a half-valid campaign.
"""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

#: Harnesses in scope (spec: harness-adapters).
REAL_HARNESSES = ("codex", "claude-code", "opencode", "hermes", "omp")
#: Harbor's built-in test agents; allowed so the runner can be exercised for free.
TEST_HARNESSES = ("oracle", "nop")
HARNESSES = REAL_HARNESSES + TEST_HARNESSES

LOCAL_PROVIDER = "local"


class ConfigError(Exception):
    """One or more configuration problems. ``problems`` lists each one."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(f"- {p}" for p in problems))


@dataclass(frozen=True)
class ConfigRoot:
    """Where configuration lives. Defaults to ``<repo>/configs``."""

    path: Path

    @property
    def runs(self) -> Path:
        return self.path / "runs"

    @property
    def campaigns(self) -> Path:
        return self.path / "campaigns"

    @property
    def arms(self) -> Path:
        return self.path / "arms"

    @property
    def toolkits(self) -> Path:
        return self.path / "toolkits"

    @property
    def serving(self) -> Path:
        return self.path / "serving"


class RunConfig(BaseModel):
    """One harness x model x arm x toolkit (x serving profile) combination."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    harness: Literal["codex", "claude-code", "opencode", "hermes", "omp", "oracle", "nop"]
    harness_version: str | None = None
    model: str | None = Field(default=None, description="'<provider>/<model id>'")
    effort: str | None = None
    arm: str = "stock"
    toolkit: str = "none"
    serving_profile: str | None = None

    @property
    def is_test_harness(self) -> bool:
        return self.harness in TEST_HARNESSES

    @property
    def provider(self) -> str | None:
        return self.model.split("/", 1)[0] if self.model else None

    @property
    def is_local(self) -> bool:
        return self.provider == LOCAL_PROVIDER

    @model_validator(mode="after")
    def _check_required(self) -> RunConfig:
        problems = []
        if not self.is_test_harness:
            for fld in ("harness_version", "model", "effort"):
                if not getattr(self, fld):
                    problems.append(f"missing required field '{fld}'")
            if self.model and "/" not in self.model:
                problems.append(f"model '{self.model}' must look like '<provider>/<model id>'")
        if self.is_local and not self.serving_profile:
            problems.append("local model requires 'serving_profile'")
        if self.serving_profile and not self.is_local:
            problems.append("'serving_profile' is only valid with a 'local/...' model")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class TaskSelector(BaseModel):
    """Which tasks a campaign runs: path globs, then optional metadata filters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    include: list[str] = Field(min_length=1, description="Globs relative to the repo root")
    repos: list[str] = Field(default_factory=list)
    tracks: list[Literal["coding", "investigative"]] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class GpuPlan(BaseModel):
    """GPU split for a campaign (spec: local-model-serving). Values are GPU UUIDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    serving_gpu: str | None = None
    task_gpu: str | None = None


class CampaignConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    runs: list[str] = Field(min_length=1)
    repeats: int = Field(default=3, ge=1)
    tasks: TaskSelector
    gpu: GpuPlan = Field(default_factory=GpuPlan)


@dataclass
class Campaign:
    """A validated campaign with its run configurations resolved."""

    config: CampaignConfig
    runs: list[RunConfig]
    task_dirs: list[Path] = field(default_factory=list)


def _read_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _fmt_validation(prefix: str, err: ValidationError) -> list[str]:
    out = []
    for e in err.errors():
        loc = ".".join(str(x) for x in e["loc"])
        msg = e["msg"].removeprefix("Value error, ")
        out.append(f"{prefix}: {loc + ': ' if loc else ''}{msg}")
    return out


def _check_references(run: RunConfig, root: ConfigRoot) -> list[str]:
    problems = []
    where = f"run '{run.name}'"
    if not (root.arms / run.arm).is_dir():
        problems.append(f"{where}: unknown arm '{run.arm}' (no {root.arms / run.arm})")
    if not (root.toolkits / run.toolkit).is_dir():
        problems.append(
            f"{where}: unknown toolkit '{run.toolkit}' (no {root.toolkits / run.toolkit})"
        )
    if run.serving_profile and not (root.serving / f"{run.serving_profile}.yaml").is_file():
        problems.append(
            f"{where}: unknown serving profile '{run.serving_profile}' "
            f"(no {root.serving / (run.serving_profile + '.yaml')})"
        )
    return problems


def load_run(name: str, root: ConfigRoot) -> RunConfig:
    """Load and fully validate one run configuration by name."""
    path = root.runs / f"{name}.toml"
    if not path.is_file():
        raise ConfigError([f"run '{name}': no such file {path}"])
    data = _read_toml(path)
    data.setdefault("name", name)
    try:
        run = RunConfig(**data)
    except ValidationError as err:
        raise ConfigError(_fmt_validation(f"run '{name}'", err)) from None
    problems = _check_references(run, root)
    if problems:
        raise ConfigError(problems)
    return run


def _task_meta(task_dir: Path) -> dict:
    toml_path = task_dir / "task.toml"
    if not toml_path.is_file():
        return {}
    return _read_toml(toml_path).get("metadata", {}) or {}


def select_tasks(selector: TaskSelector, repo_root: Path) -> list[Path]:
    """Resolve a task selector to task directories (those containing task.toml)."""
    found: set[Path] = set()
    for pattern in selector.include:
        for match in repo_root.glob(pattern):
            if (match / "task.toml").is_file():
                found.add(match)
    selected = []
    for task_dir in sorted(found):
        rel = task_dir.relative_to(repo_root).as_posix()
        if any(fnmatch.fnmatch(rel, pat) for pat in selector.exclude):
            continue
        meta = _task_meta(task_dir)
        if selector.repos and meta.get("repo") not in selector.repos:
            continue
        if selector.tracks and meta.get("track") not in selector.tracks:
            continue
        selected.append(task_dir)
    return selected


def load_campaign(name: str, root: ConfigRoot, repo_root: Path) -> Campaign:
    """Load a campaign, validate it and every run it names, and resolve its tasks.

    Raises ConfigError listing *all* problems found, before anything is started.
    """
    path = root.campaigns / f"{name}.toml"
    if not path.is_file():
        raise ConfigError([f"campaign '{name}': no such file {path}"])
    data = _read_toml(path)
    data.setdefault("name", name)
    try:
        cfg = CampaignConfig(**data)
    except ValidationError as err:
        raise ConfigError(_fmt_validation(f"campaign '{name}'", err)) from None

    problems: list[str] = []
    runs: list[RunConfig] = []
    for run_name in cfg.runs:
        try:
            runs.append(load_run(run_name, root))
        except ConfigError as err:
            problems.extend(err.problems)
    if len(set(cfg.runs)) != len(cfg.runs):
        problems.append(f"campaign '{name}': duplicate run names in 'runs'")

    tasks = select_tasks(cfg.tasks, repo_root)
    if not tasks:
        problems.append(f"campaign '{name}': task selection matched no tasks")

    if problems:
        raise ConfigError(problems)
    return Campaign(config=cfg, runs=runs, task_dirs=tasks)
