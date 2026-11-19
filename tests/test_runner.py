import datetime as dt
import json
from pathlib import Path

import pytest

from fitting_room.config import (
    Campaign,
    CampaignConfig,
    ConfigError,
    ConfigRoot,
    RunConfig,
    TaskSelector,
)
from fitting_room.provenance import SIDECAR_NAME
from fitting_room.runner import JOB_CONFIG_NAME, run_campaign, trial_dirs

NOW = dt.datetime(2026, 11, 17, 3, 0, 0)


def ROOT(tmp_path: Path) -> ConfigRoot:
    cfg = tmp_path / "configs"
    for d in ("arms/stock", "toolkits/none"):
        (cfg / d).mkdir(parents=True, exist_ok=True)
    (cfg / "arms/stock/system_append.md").write_text("")
    return ConfigRoot(cfg)


def make_campaign(tmp_path: Path, runs: list[RunConfig], repeats: int = 3) -> Campaign:
    tasks = []
    for name in ("t1", "t2"):
        d = tmp_path / "tasks" / name
        d.mkdir(parents=True)
        (d / "task.toml").write_text("")
        tasks.append(d)
    cfg = CampaignConfig(
        name="camp",
        runs=[r.name for r in runs],
        repeats=repeats,
        tasks=TaskSelector(include=["tasks/*"]),
    )
    return Campaign(config=cfg, runs=runs, task_dirs=tasks)


def fake_harbor(calls: list[dict]):
    """Pretend to be Harbor: record the job config and create one trial per attempt."""

    def invoke(cfg_path: Path, host_env: dict) -> int:
        cfg = json.loads(cfg_path.read_text())
        calls.append({**cfg, "_host_env": host_env})
        job_dir = Path(cfg["jobs_dir"]) / cfg["job_name"]
        for task in cfg["tasks"]:
            for i in range(cfg["n_attempts"]):
                trial = job_dir / f"{Path(task['path']).name}__{i}"
                trial.mkdir(parents=True)
                result = {"trial_name": trial.name, "task_id": {"path": task["path"]}}
                (trial / "result.json").write_text(json.dumps(result))
        return 0

    return invoke


def test_one_job_per_run_config_with_repeats(tmp_path):
    runs = [RunConfig(name="a", harness="oracle"), RunConfig(name="b", harness="nop")]
    calls: list[dict] = []
    jobs = run_campaign(
        make_campaign(tmp_path, runs),
        tmp_path / "results",
        ROOT(tmp_path),
        invoke=fake_harbor(calls),
        now=NOW,
    )

    assert [c["job_name"] for c in calls] == ["a", "b"]
    assert all(c["n_attempts"] == 3 for c in calls)
    assert calls[0]["agents"] == [{"name": "oracle"}]
    assert len(calls[0]["tasks"]) == 2
    # 2 configs x 2 tasks x 3 repeats
    assert sum(len(trial_dirs(j.job_dir)) for j in jobs) == 12
    # job config kept for provenance, under results/<campaign>/<stamp>/<run>/
    assert (tmp_path / "results/camp/20261117-030000/a" / JOB_CONFIG_NAME).is_file()


def test_unmapped_harness_refused_before_anything_starts(tmp_path):
    runs = [
        RunConfig(name="ok", harness="oracle"),
        RunConfig(
            name="real", harness="hermes", harness_version="1", model="openai/m", effort="low"
        ),
    ]
    calls: list[dict] = []
    with pytest.raises(ConfigError) as exc:
        run_campaign(
            make_campaign(tmp_path, runs),
            tmp_path / "results",
            ROOT(tmp_path),
            invoke=fake_harbor(calls),
            now=NOW,
        )
    assert "harness 'hermes' with provider 'openai' is not supported" in exc.value.problems[0]
    assert calls == []
    assert not (tmp_path / "results").exists()


def test_every_trial_gets_a_provenance_sidecar(tmp_path):
    runs = [RunConfig(name="a", harness="oracle"), RunConfig(name="b", harness="nop")]
    (tmp_path / "tasks").mkdir()
    jobs = run_campaign(
        make_campaign(tmp_path, runs, repeats=2),
        tmp_path / "results",
        ROOT(tmp_path),
        invoke=fake_harbor([]),
        now=NOW,
    )
    trials = [t for j in jobs for t in trial_dirs(j.job_dir)]
    assert len(trials) == 8
    for t in trials:
        side = json.loads((t / SIDECAR_NAME).read_text())
        assert side["run"]["name"] in ("a", "b")
        assert side["arm"]["name"] == "stock" and side["arm"]["digest"].startswith("sha256:")
        assert side["toolkit"]["name"] == "none"
        assert side["task"]["path"].endswith(("t1", "t2"))
        assert side["trial"] == t.name


def test_claude_code_glm_mapping_uses_placeholder_and_ca_overlay(tmp_path, monkeypatch):
    from fitting_room import providers

    ca = tmp_path / "av-ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\nAV\n-----END CERTIFICATE-----\n")
    monkeypatch.setattr(providers, "AGENT_VAULT_CA", ca)
    monkeypatch.setattr(providers, "SYSTEM_CA_BUNDLE", tmp_path / "missing.crt")
    run = RunConfig(
        name="cc-glm",
        harness="claude-code",
        harness_version="2.1.263",
        model="zai/glm-5.3-flash",
        effort="medium",
    )
    calls: list[dict] = []
    run_campaign(
        make_campaign(tmp_path, [run], repeats=1),
        tmp_path / "results",
        ROOT(tmp_path),
        invoke=fake_harbor(calls),
        now=NOW,
        work_dir=tmp_path / "work",
    )
    (cfg,) = calls
    agent = cfg["agents"][0]
    assert agent["name"] == "claude-code"
    assert agent["model_name"] == "anthropic/glm-5.3-flash"
    assert agent["base_url"] == "https://api.z.ai/api/anthropic"
    assert agent["model_api_key_name"] == "ANTHROPIC_AUTH_TOKEN"
    assert agent["kwargs"] == {"version": "2.1.263", "reasoning_effort": "medium"}
    assert cfg["_host_env"] == {"ANTHROPIC_AUTH_TOKEN": "av-managed-key"}
    (overlay,) = cfg["environment"]["extra_docker_compose"]
    text = Path(overlay).read_text()
    assert "NODE_EXTRA_CA_CERTS: /opt/fr-certs/agent-vault-ca.pem" in text
    assert (tmp_path / "work/certs/ca-bundle.crt").read_text().count("AV") == 1


def test_local_run_refused_when_endpoint_down(tmp_path):
    (tmp_path / "configs/serving").mkdir(parents=True)
    run = RunConfig(
        name="oc-local",
        harness="opencode",
        harness_version="2.2.6",
        model="local/qwen3.5-9b",
        effort="medium",
        serving_profile="p",
    )
    calls: list[dict] = []
    with pytest.raises(ConfigError) as exc:
        run_campaign(
            make_campaign(tmp_path, [run]),
            tmp_path / "results",
            ROOT(tmp_path),
            invoke=fake_harbor(calls),
            now=NOW,
            endpoint_check=lambda _: False,
        )
    assert "fr serve up p" in exc.value.problems[0]
    assert calls == []


def test_unsupported_pair_refused(tmp_path):
    run = RunConfig(
        name="codex-glm", harness="codex", harness_version="1", model="zai/glm-5.3", effort="low"
    )
    with pytest.raises(ConfigError) as exc:
        run_campaign(
            make_campaign(tmp_path, [run]), tmp_path / "results", ROOT(tmp_path),
            invoke=fake_harbor([]), now=NOW,
        )  # fmt: skip
    assert "not supported yet" in exc.value.problems[0]


def test_omp_glm_mapping(tmp_path, monkeypatch):
    from fitting_room.runner import agent_spec_for

    run = RunConfig(
        name="omp-glm", harness="omp", harness_version="18.12.6", model="zai/glm-5.3", effort="max"
    )
    spec = agent_spec_for(run)
    agent = spec.to_job_agent()
    assert agent["import_path"] == "fitting_room.adapters.omp:OhMyPi" and "name" not in agent
    assert agent["model_name"] == "zai/glm-5.3"
    assert agent["env"] == {"ZAI_API_KEY": "av-managed-key"}
    assert agent["kwargs"] == {"version": "18.12.6", "reasoning_effort": "max"}
    assert spec.needs_agent_vault_ca


def test_hermes_mappings():
    from fitting_room.runner import agent_spec_for

    sha = "f97608f178d1ffeca59860195ab7da295f7c8e5f"
    glm = agent_spec_for(
        RunConfig(name="h", harness="hermes", harness_version=sha,
                  model="zai/glm-5.3-flash", effort="medium")
    )  # fmt: skip
    assert glm.model_name == "zai/glm-5.3-flash"
    assert glm.env["GLM_API_KEY"] == "av-managed-key"
    assert glm.env["GLM_BASE_URL"].endswith("/api/coding/paas/v4")
    assert glm.needs_agent_vault_ca and glm.kwargs["reasoning_effort"] == "medium"
    local = agent_spec_for(
        RunConfig(name="h", harness="hermes", harness_version=sha, model="local/qwen3.5-9b",
                  effort="low", serving_profile="qwen35-9b-3080")
    )  # fmt: skip
    # Hermes rejects keys that look like placeholders ("placeholder", "dummy", "sk-...").
    assert local.env["OPENAI_API_KEY"] == "no-key-required"
    assert local.base_url.startswith("http://host.docker.internal")


def test_hermes_refuses_thinking_off():
    from fitting_room.adapters.hermes import FrHermesOptions

    with pytest.raises(ValueError):
        FrHermesOptions(reasoning_effort="none")
    with pytest.raises(ValueError):
        FrHermesOptions()


def test_codex_local_mapping_and_no_host_login(monkeypatch, tmp_path):
    from fitting_room import runner

    spec = runner.agent_spec_for(
        RunConfig(name="c", harness="codex", harness_version="0.163.0", model="local/qwen3.5-9b",
                  effort="medium", serving_profile="qwen35-9b-3080")
    )  # fmt: skip
    assert spec.name == "codex" and spec.base_url.endswith("/v1")
    assert spec.kwargs["reasoning_effort"] == "medium"
    # Harbor uploads ~/.codex/auth.json when these are set; fr never passes them on.
    seen = {}
    monkeypatch.setenv("CODEX_FORCE_AUTH_JSON", "1")
    monkeypatch.setattr(runner.subprocess, "call", lambda cmd, env: seen.update(env) or 0)
    runner.invoke_harbor(tmp_path / "job.json", {"OPENAI_API_KEY": "no-key-required"})
    assert "CODEX_FORCE_AUTH_JSON" not in seen and seen["OPENAI_API_KEY"] == "no-key-required"


def _dev_stack(cfg_root: ConfigRoot) -> None:
    tk = cfg_root.toolkits / "dev-stack"
    (tk / "skills" / "cbm").mkdir(parents=True)
    (tk / "skills" / "cbm" / "SKILL.md").write_text("---\nname: cbm\n---\n")
    (tk / "toolkit.toml").write_text(
        'name = "dev-stack"\n'
        'dockerfile_append = "RUN /opt/fr-toolkit/setup.sh"\n'
        '[[items]]\nname = "bd"\nkind = "cli"\n'
        '[[items]]\nname = "codebase-memory"\nkind = "mcp"\ncommand = "codebase-memory-mcp"\n'
        '[[items]]\nname = "cbm-skill"\nkind = "skill"\npath = "skills/cbm"\n'
    )


def _local_run(harness: str, version: str, toolkit: str) -> RunConfig:
    return RunConfig(name=f"{harness}-{toolkit}", harness=harness, harness_version=version,
                     model="local/qwen3.5-9b", effort="medium", toolkit=toolkit,
                     serving_profile="qwen35-9b-3080")  # fmt: skip


def test_dev_stack_stages_tasks_and_registers_mcp_and_skills(tmp_path):
    root = ROOT(tmp_path)
    _dev_stack(root)
    camp = make_campaign(tmp_path, [_local_run("codex", "0.163.0", "dev-stack")], repeats=1)
    for d in camp.task_dirs:
        (d / "environment").mkdir()
        (d / "environment" / "Dockerfile").write_text("FROM fr-repo/x:latest\n")
    calls: list[dict] = []
    run_campaign(camp, tmp_path / "results", root, invoke=fake_harbor(calls), now=NOW,
                 work_dir=tmp_path / "work", endpoint_check=lambda _: True)  # fmt: skip
    agent = calls[0]["agents"][0]
    assert agent["mcp_servers"][0]["command"] == "codebase-memory-mcp"
    assert agent["skills"][0].endswith("skills/cbm")
    staged = Path(calls[0]["tasks"][0]["path"])
    assert staged.is_relative_to(tmp_path / "work" / "staged" / "dev-stack")
    assert (
        staged.joinpath("environment/Dockerfile")
        .read_text()
        .endswith("RUN /opt/fr-toolkit/setup.sh\n")
    )
    # The original task is untouched; other files are hardlinks, not copies.
    original = camp.task_dirs[0]
    assert original.joinpath("environment/Dockerfile").read_text() == "FROM fr-repo/x:latest\n"
    assert (
        staged.joinpath("task.toml").stat().st_ino == original.joinpath("task.toml").stat().st_ino
    )


def test_toolkit_none_adds_nothing(tmp_path):
    camp = make_campaign(tmp_path, [_local_run("codex", "0.163.0", "none")], repeats=1)
    calls: list[dict] = []
    run_campaign(camp, tmp_path / "results", ROOT(tmp_path), invoke=fake_harbor(calls), now=NOW,
                 work_dir=tmp_path / "work", endpoint_check=lambda _: True)  # fmt: skip
    agent = calls[0]["agents"][0]
    assert "mcp_servers" not in agent and "skills" not in agent
    assert [Path(t["path"]) for t in calls[0]["tasks"]] == [d.resolve() for d in camp.task_dirs]


def test_harness_without_item_support_refused(tmp_path):
    root = ROOT(tmp_path)
    _dev_stack(root)
    with (root.toolkits / "dev-stack" / "toolkit.toml").open("a") as fh:
        fh.write('[[items]]\nname = "bd-prime"\nkind = "hook"\n')
    run = RunConfig(name="omp-dev", harness="omp", harness_version="18.12.6",
                    model="zai/glm-5.3-flash", effort="medium", toolkit="dev-stack")  # fmt: skip
    calls: list[dict] = []
    with pytest.raises(ConfigError) as err:
        run_campaign(make_campaign(tmp_path, [run]), tmp_path / "results", root,
                     invoke=fake_harbor(calls), now=NOW)  # fmt: skip
    assert "bd-prime (hook)" in str(err.value.problems)
    assert calls == []
