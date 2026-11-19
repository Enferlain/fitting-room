"""Execute campaigns through Harbor (spec: benchmark-runs; design D4).

One Harbor job per run configuration, so every trial in a job shares exactly one
resolved configuration (harness, model, arm, toolkit, serving profile). Harbor is
driven through its CLI with a generated JobConfig file, which is kept next to the
results for provenance.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from fitting_room.config import Campaign, ConfigError, ConfigRoot, RunConfig
from fitting_room.provenance import write_sidecars
from fitting_room.providers import PROVIDERS, stage_certs, write_ca_overlay
from fitting_room.toolkits import Toolkit, load_toolkit, stage_tasks, unsupported

JOB_CONFIG_NAME = "job-config.json"
# Variables that make Harbor upload a host login (e.g. ~/.codex/auth.json) into the
# sandbox. Benchmarks never use subscription logins, so they are never passed through.
HOST_LOGIN_VARS = frozenset({"CODEX_AUTH_JSON_PATH", "CODEX_FORCE_AUTH_JSON"})


@dataclass(frozen=True)
class AgentSpec:
    """How Harbor should run one harness for one run configuration."""

    name: str | None = None
    import_path: str | None = None
    model_name: str | None = None
    kwargs: dict | None = None
    env: dict | None = None
    base_url: str | None = None
    api_key_name: str | None = None
    # Placeholder credentials Harbor must find in its own environment (never real keys).
    host_env: dict = field(default_factory=dict)
    needs_agent_vault_ca: bool = False
    extra_allowed_hosts: tuple[str, ...] = ()

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
        if self.base_url:
            out["base_url"] = self.base_url
        if self.api_key_name:
            out["model_api_key_name"] = self.api_key_name
        if self.extra_allowed_hosts:
            out["extra_allowed_hosts"] = list(self.extra_allowed_hosts)
        return out


def _model_id(run: RunConfig) -> str:
    return (run.model or "").split("/", 1)[1]


def _claude_code_zai(run: RunConfig) -> AgentSpec:
    p = PROVIDERS["zai"]
    return AgentSpec(
        name="claude-code",
        model_name=f"anthropic/{_model_id(run)}",
        kwargs={"version": run.harness_version, "reasoning_effort": run.effort},
        base_url=p.anthropic_base_url,
        api_key_name="ANTHROPIC_AUTH_TOKEN",
        host_env={"ANTHROPIC_AUTH_TOKEN": p.placeholder_key},
        needs_agent_vault_ca=True,
        extra_allowed_hosts=p.allowed_hosts,
    )


def _opencode_local(run: RunConfig) -> AgentSpec:
    # OpenCode expresses effort as a model variant; llama.cpp models have none, so the
    # configured effort is recorded in the sidecar but not passed.
    p = PROVIDERS["local"]
    return AgentSpec(
        name="opencode-v2",
        model_name=f"openai/{_model_id(run)}",
        kwargs={"version": run.harness_version},
        base_url=p.openai_base_url,
        host_env={"OPENAI_API_KEY": p.placeholder_key},
        extra_allowed_hosts=p.allowed_hosts,
    )


def _omp_zai(run: RunConfig) -> AgentSpec:
    # Oh My Pi's built-in zai provider reads ZAI_API_KEY and picks z.ai's API per model.
    p = PROVIDERS["zai"]
    key = {"ZAI_API_KEY": p.placeholder_key}
    return AgentSpec(
        import_path="fitting_room.adapters.omp:OhMyPi",
        model_name=f"zai/{_model_id(run)}",
        kwargs={"version": run.harness_version, "reasoning_effort": run.effort},
        api_key_name="ZAI_API_KEY",
        env=key,
        host_env=key,
        needs_agent_vault_ca=True,
        extra_allowed_hosts=p.allowed_hosts,
    )


def _codex_local(run: RunConfig) -> AgentSpec:
    # Codex only speaks the Responses API; llama-server serves /v1/responses.
    p = PROVIDERS["local"]
    return AgentSpec(
        name="codex",
        model_name=f"openai/{_model_id(run)}",
        kwargs={
            "version": run.harness_version,
            "reasoning_effort": run.effort,
            "disable_web_search": True,
        },
        base_url=p.openai_base_url,
        host_env={"OPENAI_API_KEY": p.placeholder_key},
        extra_allowed_hosts=p.allowed_hosts,
    )


def _hermes(run: RunConfig) -> AgentSpec:
    # Hermes's native zai provider reads GLM_API_KEY; GLM_BASE_URL pins the coding endpoint.
    # Local models go through its OpenAI provider, which honours OPENAI_BASE_URL.
    p = PROVIDERS[run.provider or ""]
    common = {
        "import_path": "fitting_room.adapters.hermes:FrHermes",
        "kwargs": {"version": run.harness_version, "reasoning_effort": run.effort},
        "extra_allowed_hosts": p.allowed_hosts,
    }
    if run.provider == "zai":
        key = {"GLM_API_KEY": p.placeholder_key}
        return AgentSpec(
            model_name=f"zai/{_model_id(run)}",
            api_key_name="GLM_API_KEY",
            env={**key, "GLM_BASE_URL": p.openai_base_url or ""},
            host_env=key,
            needs_agent_vault_ca=True,
            **common,
        )
    key = {"OPENAI_API_KEY": p.placeholder_key}
    return AgentSpec(
        model_name=f"openai/{_model_id(run)}",
        base_url=p.openai_base_url,
        api_key_name="OPENAI_API_KEY",
        env=key,
        host_env=key,
        **common,
    )


#: Harness x provider pairs that have passed a smoke run (docs/harnesses.md).
#: Anything else is refused rather than scored.
SUPPORTED: dict[tuple[str, str], Callable[[RunConfig], AgentSpec]] = {
    ("claude-code", "zai"): _claude_code_zai,
    ("opencode", "local"): _opencode_local,
    ("omp", "zai"): _omp_zai,
    ("codex", "local"): _codex_local,
    ("hermes", "zai"): _hermes,
    ("hermes", "local"): _hermes,
}


def agent_spec_for(run: RunConfig) -> AgentSpec:
    """Map a run configuration to a Harbor agent."""
    if run.harness in ("oracle", "nop"):
        return AgentSpec(name=run.harness)
    build = SUPPORTED.get((run.harness, run.provider or ""))
    if build is None:
        raise ConfigError(
            [
                f"run '{run.name}': harness '{run.harness}' with provider '{run.provider}' "
                "is not supported yet (no passing smoke run)"
            ]
        )
    return build(run)


def build_job_config(
    run: RunConfig,
    task_dirs: list[Path],
    repeats: int,
    jobs_dir: Path,
    agent: AgentSpec,
    extra_compose: list[Path] | None = None,
    toolkit: Toolkit | None = None,
) -> dict:
    job_agent = agent.to_job_agent()
    if toolkit is not None and agent.name not in ("oracle", "nop"):
        if servers := toolkit.mcp_servers():
            job_agent["mcp_servers"] = servers
        if skills := toolkit.skill_dirs():
            job_agent["skills"] = skills
    cfg = {
        "job_name": run.name,
        "jobs_dir": str(jobs_dir),
        "n_attempts": repeats,
        "quiet": True,
        "agents": [job_agent],
        "tasks": [{"path": str(p)} for p in task_dirs],
    }
    if extra_compose:
        cfg["environment"] = {"extra_docker_compose": [str(p) for p in extra_compose]}
    return cfg


@dataclass
class JobResult:
    run: RunConfig
    job_dir: Path
    returncode: int


HarborInvoker = Callable[[Path, dict], int]


def invoke_harbor(job_config_path: Path, host_env: dict) -> int:
    """Run `harbor run -c <file>` with placeholder credentials in its environment."""
    env = {k: v for k, v in os.environ.items() if k not in HOST_LOGIN_VARS}
    env.update(host_env)
    return subprocess.call(["harbor", "run", "-c", str(job_config_path), "-y", "-q"], env=env)


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
    work_dir: Path | None = None,
    endpoint_check: Callable[[str], bool] | None = None,
) -> list[JobResult]:
    """Run every configuration of a validated campaign. Validation already happened in
    load_campaign; agent mapping is checked for *all* runs before the first job starts."""
    specs: dict[str, AgentSpec] = {}
    problems: list[str] = []
    toolkits: dict[str, Toolkit] = {}
    for run in campaign.runs:
        try:
            specs[run.name] = agent_spec_for(run)
        except ConfigError as err:
            problems.extend(err.problems)
        try:
            toolkits[run.name] = load_toolkit(root.toolkits, run.toolkit)
        except ValueError as err:
            problems.append(f"run '{run.name}': {err}")
            continue
        if bad := unsupported(run.harness, toolkits[run.name]):
            problems.append(
                f"run '{run.name}': harness {run.harness} cannot use toolkit "
                f"'{run.toolkit}' items: {', '.join(bad)}"
            )
    if endpoint_check is None:
        from fitting_room.serving.launcher import endpoint_up as endpoint_check
    for run in campaign.runs:
        if run.is_local and not endpoint_check("127.0.0.1:18080"):
            problems.append(
                f"run '{run.name}': local endpoint 127.0.0.1:18080 is not up "
                f"(run `fr serve up {run.serving_profile}` first)"
            )
    if problems:
        raise ConfigError(problems)

    out_dir = campaign_output_dir(results_root, campaign.config.name, now)
    out_dir.mkdir(parents=True, exist_ok=False)
    results = []
    work = work_dir or results_root.parent / "work"
    for run in campaign.runs:
        toolkit = toolkits[run.name]
        tasks = stage_tasks(
            [p.resolve() for p in campaign.task_dirs], toolkit, (work / "staged").resolve()
        )
        job_dir = out_dir / run.name
        job_dir.mkdir()
        spec = specs[run.name]
        overlays = []
        if spec.needs_agent_vault_ca:
            certs = stage_certs(work)
            overlays.append(
                write_ca_overlay(certs, job_dir / "agent-vault-ca.compose.yaml").resolve()
            )
        job_cfg = build_job_config(
            run,
            tasks,
            campaign.config.repeats,
            out_dir.resolve(),
            spec,
            extra_compose=overlays or None,
            toolkit=toolkit,
        )
        cfg_path = job_dir / JOB_CONFIG_NAME
        cfg_path.write_text(json.dumps(job_cfg, indent=2) + "\n")
        rc = invoke(cfg_path, spec.host_env)
        write_sidecars(job_dir, run, root, campaign.config.name)
        results.append(JobResult(run=run, job_dir=job_dir, returncode=rc))
    return results


def trial_dirs(job_dir: Path) -> list[Path]:
    """Trial directories of a Harbor job (each holds a result.json)."""
    return sorted(p.parent for p in job_dir.glob("*/result.json"))
