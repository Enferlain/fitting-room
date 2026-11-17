"""Execute campaigns through Harbor (spec: benchmark-runs; design D4).

One Harbor job per run configuration, so every trial in a job shares exactly one
resolved configuration (harness, model, arm, toolkit, serving profile). Harbor is
driven through its CLI with a generated JobConfig file, which is kept next to the
results for provenance.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fitting_room.config import Campaign, ConfigError, ConfigRoot, RunConfig
from fitting_room.provenance import write_sidecars

JOB_CONFIG_NAME = "job-config.json"


@dataclass(frozen=True)
class AgentSpec:
    """How Harbor should run one harness for one run configuration."""

    name: str | None = None
    import_path: str | None = None
    model_name: str | None = None
    kwargs: dict | None = None
    env: dict | None = None

    def to_job_agent(self) -> dict:
        out: dict = {}
        if self.import_path:
            out["import_path"] = self.import_path
        else:
            out["name"] = self.name
        if self.model_name:
            out["model_name"] = self.model_name
        if self.kwargs:
            out["kwargs"] = self.kwargs
        if self.env:
            out["env"] = self.env
        return out


def agent_spec_for(run: RunConfig) -> AgentSpec:
    """Map a run configuration to a Harbor agent. Real harnesses arrive in group 4."""
    if run.harness in ("oracle", "nop"):
        return AgentSpec(name=run.harness)
    raise ConfigError([f"run '{run.name}': adapter for harness '{run.harness}' not implemented"])


def build_job_config(
    run: RunConfig,
    task_dirs: list[Path],
    repeats: int,
    jobs_dir: Path,
    agent: AgentSpec,
) -> dict:
    return {
        "job_name": run.name,
        "jobs_dir": str(jobs_dir),
        "n_attempts": repeats,
        "quiet": True,
        "agents": [agent.to_job_agent()],
        "tasks": [{"path": str(p)} for p in task_dirs],
    }


@dataclass
class JobResult:
    run: RunConfig
    job_dir: Path
    returncode: int


HarborInvoker = Callable[[Path], int]


def invoke_harbor(job_config_path: Path) -> int:
    """Run `harbor run -c <file>`; returns the exit code."""
    return subprocess.call(["harbor", "run", "-c", str(job_config_path), "-y", "-q"])


def campaign_output_dir(results_root: Path, campaign_name: str, now: dt.datetime | None) -> Path:
    stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    return results_root / campaign_name / stamp


def run_campaign(
    campaign: Campaign,
    results_root: Path,
    root: ConfigRoot,
    *,
    invoke: HarborInvoker = invoke_harbor,
    now: dt.datetime | None = None,
) -> list[JobResult]:
    """Run every configuration of a validated campaign. Validation already happened in
    load_campaign; agent mapping is checked for *all* runs before the first job starts."""
    specs: dict[str, AgentSpec] = {}
    problems: list[str] = []
    for run in campaign.runs:
        try:
            specs[run.name] = agent_spec_for(run)
        except ConfigError as err:
            problems.extend(err.problems)
    if problems:
        raise ConfigError(problems)

    out_dir = campaign_output_dir(results_root, campaign.config.name, now)
    out_dir.mkdir(parents=True, exist_ok=False)
    results = []
    for run in campaign.runs:
        job_cfg = build_job_config(
            run,
            [p.resolve() for p in campaign.task_dirs],
            campaign.config.repeats,
            out_dir.resolve(),
            specs[run.name],
        )
        job_dir = out_dir / run.name
        job_dir.mkdir()
        cfg_path = job_dir / JOB_CONFIG_NAME
        cfg_path.write_text(json.dumps(job_cfg, indent=2) + "\n")
        rc = invoke(cfg_path)
        write_sidecars(job_dir, run, root, campaign.config.name)
        results.append(JobResult(run=run, job_dir=job_dir, returncode=rc))
    return results


def trial_dirs(job_dir: Path) -> list[Path]:
    """Trial directories of a Harbor job (each holds a result.json)."""
    return sorted(p.parent for p in job_dir.glob("*/result.json"))
