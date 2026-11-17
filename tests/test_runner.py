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

    def invoke(cfg_path: Path) -> int:
        cfg = json.loads(cfg_path.read_text())
        calls.append(cfg)
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
    assert "harness 'hermes' not implemented" in exc.value.problems[0]
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
