from pathlib import Path

import pytest

from fitting_room.config import ConfigError, ConfigRoot, load_campaign, load_run


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    cfg = tmp_path / "configs"
    for d in ("runs", "campaigns", "arms/stock", "toolkits/none", "serving"):
        (cfg / d).mkdir(parents=True)
    (cfg / "serving" / "qwen-3090.yaml").write_text("models: {}\n")
    task = tmp_path / "tasks" / "demo" / "t1"
    task.mkdir(parents=True)
    (task / "task.toml").write_text('[metadata]\nrepo = "demo"\ntrack = "coding"\n')
    return tmp_path


def root(repo: Path) -> ConfigRoot:
    return ConfigRoot(repo / "configs")


def write_run(repo: Path, name: str, body: str) -> None:
    (repo / "configs" / "runs" / f"{name}.toml").write_text(body)


GOOD = 'harness = "codex"\nharness_version = "0.162.0"\nmodel = "openai/m1"\neffort = "medium"\n'


def problems_for(repo: Path, name: str) -> str:
    with pytest.raises(ConfigError) as exc:
        load_run(name, root(repo))
    return "\n".join(exc.value.problems)


def test_complete_configuration_accepted_with_defaults(repo):
    write_run(repo, "good", GOOD)
    run = load_run("good", root(repo))
    assert (run.name, run.harness, run.arm, run.toolkit) == ("good", "codex", "stock", "none")
    assert run.provider == "openai" and not run.is_local


def test_missing_harness_version_rejected(repo):
    write_run(repo, "r", GOOD.replace('harness_version = "0.162.0"\n', ""))
    assert "harness_version" in problems_for(repo, "r")


def test_missing_effort_rejected(repo):
    write_run(repo, "r", GOOD.replace('effort = "medium"\n', ""))
    assert "effort" in problems_for(repo, "r")


def test_local_model_without_serving_profile_rejected(repo):
    write_run(repo, "r", GOOD.replace("openai/m1", "local/qwen"))
    assert "serving_profile" in problems_for(repo, "r")


def test_local_model_with_existing_serving_profile_accepted(repo):
    write_run(
        repo, "r", GOOD.replace("openai/m1", "local/qwen") + 'serving_profile = "qwen-3090"\n'
    )
    run = load_run("r", root(repo))
    assert run.is_local and run.serving_profile == "qwen-3090"


def test_unknown_serving_profile_rejected(repo):
    write_run(repo, "r", GOOD.replace("openai/m1", "local/qwen") + 'serving_profile = "nope"\n')
    assert "unknown serving profile 'nope'" in problems_for(repo, "r")


def test_serving_profile_with_hosted_model_rejected(repo):
    write_run(repo, "r", GOOD + 'serving_profile = "qwen-3090"\n')
    assert "only valid with a 'local/" in problems_for(repo, "r")


def test_unknown_arm_rejected(repo):
    write_run(repo, "r", GOOD + 'arm = "persona-x"\n')
    assert "unknown arm 'persona-x'" in problems_for(repo, "r")


def test_unknown_toolkit_rejected(repo):
    write_run(repo, "r", GOOD + 'toolkit = "dev-stack"\n')
    assert "unknown toolkit 'dev-stack'" in problems_for(repo, "r")


def test_unknown_harness_rejected(repo):
    write_run(repo, "r", GOOD.replace('"codex"', '"aider"'))
    assert "harness" in problems_for(repo, "r")


def test_unknown_field_rejected(repo):
    write_run(repo, "r", GOOD + "temprature = 0.2\n")
    assert "temprature" in problems_for(repo, "r")


def test_test_harness_needs_no_model(repo):
    write_run(repo, "o", 'harness = "oracle"\n')
    assert load_run("o", root(repo)).is_test_harness


def test_campaign_reports_all_problems_at_once(repo):
    write_run(repo, "a", GOOD.replace('effort = "medium"\n', ""))
    write_run(repo, "b", GOOD + 'arm = "missing"\n')
    (repo / "configs" / "campaigns" / "c.toml").write_text(
        'runs = ["a", "b", "ghost"]\n[tasks]\ninclude = ["tasks/*/*"]\n'
    )
    with pytest.raises(ConfigError) as exc:
        load_campaign("c", root(repo), repo)
    text = "\n".join(exc.value.problems)
    assert "effort" in text and "unknown arm 'missing'" in text and "ghost" in text


def test_campaign_resolves_runs_tasks_and_default_repeats(repo):
    write_run(repo, "a", GOOD)
    (repo / "configs" / "campaigns" / "c.toml").write_text(
        'runs = ["a"]\n[tasks]\ninclude = ["tasks/*/*"]\ntracks = ["coding"]\n'
    )
    camp = load_campaign("c", root(repo), repo)
    assert camp.config.repeats == 3
    assert [r.name for r in camp.runs] == ["a"]
    assert [p.name for p in camp.task_dirs] == ["t1"]


def test_campaign_with_no_matching_tasks_rejected(repo):
    write_run(repo, "a", GOOD)
    (repo / "configs" / "campaigns" / "c.toml").write_text(
        'runs = ["a"]\n[tasks]\ninclude = ["tasks/*/*"]\nrepos = ["other"]\n'
    )
    with pytest.raises(ConfigError) as exc:
        load_campaign("c", root(repo), repo)
    assert "matched no tasks" in exc.value.problems[0]
