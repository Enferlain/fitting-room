import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from fitting_room.podman_host import BASE_IMAGE
from fitting_room.tasks.check import TEST_SH, CheckError, assemble


def _task(tmp_path: Path) -> Path:
    task = tmp_path / "my-task"
    (task / "tests").mkdir(parents=True)
    (task / "solution").mkdir()
    (task / "environment" / "repo" / "src").mkdir(parents=True)
    (task / "task.toml").write_text(
        '[metadata]\nrepo = "data-processing"\nstart_commit = "abc123"\n'
        '[environment]\ndocker_image = "localhost/fr-base/cpu:1"\n'
    )
    (task / "instruction.md").write_text("Fix the bug.\n")
    (task / "tests" / "test.sh").write_text("#!/bin/bash\n")
    (task / "solution" / "solve.sh").write_text("#!/bin/bash\n")
    (task / "environment" / "repo" / "src" / "big.py").write_text("x = 1\n")
    (task / "environment" / ".materialized.json").write_text("{}")
    return task


def test_wrapper_omits_snapshot_and_uses_base_image(tmp_path):
    wrapper = assemble(_task(tmp_path), tmp_path / "out")
    cfg = tomllib.loads((wrapper / "task.toml").read_text())
    assert cfg["environment"]["docker_image"] == BASE_IMAGE
    assert cfg["verifier"]["environment_mode"] == "shared"
    assert cfg["agent"]["network_mode"] == "allowlist"
    assert "repo" not in cfg["metadata"]  # wrapper must not get a snapshot mount
    copied = wrapper / "environment" / "task"
    assert (copied / "instruction.md").is_file()
    assert (copied / "tests" / "test.sh").is_file()
    assert (copied / "environment" / ".materialized.json").is_file()
    assert not (copied / "environment" / "repo").exists()
    assert not (wrapper / "tests" / "validate.py").exists()
    criteria = json.loads((wrapper / "tests" / "criteria.json").read_text())
    assert "anti_cheating_measures" in criteria
    instruction = (wrapper / "instruction.md").read_text()
    assert "environment/repo/big.py" not in instruction
    assert "`data-processing`" in instruction and "abc123" in instruction
    assert "check-result.json" in instruction


def test_refuses_non_task(tmp_path):
    with pytest.raises(CheckError):
        assemble(tmp_path, tmp_path / "out")


@pytest.fixture
def run_validator(tmp_path):
    if shutil.which("jq") is None:
        pytest.skip("jq not installed")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "criteria.json").write_text(json.dumps(["a", "b"]))
    script = (
        TEST_SH.replace("/tests/", f"{tests}/")
        .replace("/app/check-result.json", str(tmp_path / "result.json"))
        .replace("/logs/verifier", str(tmp_path / "logs"))
        .replace("/tmp/check-errors.txt", str(tmp_path / "errors.txt"))
    )
    (tmp_path / "test.sh").write_text(script)

    def run(result) -> tuple[str, str]:
        if result is not None:
            (tmp_path / "result.json").write_text(
                result if isinstance(result, str) else json.dumps(result)
            )
        out = subprocess.run(["bash", str(tmp_path / "test.sh")], capture_output=True, text=True)
        return (tmp_path / "logs" / "reward.txt").read_text().strip(), out.stdout

    return run


def test_validator_accepts_valid(run_validator):
    ok = {
        "a": {"outcome": "pass", "explanation": "x"},
        "b": {"outcome": "fail", "explanation": "y"},
    }
    assert run_validator(ok)[0] == "1"


@pytest.mark.parametrize(
    "result, message",
    [
        (None, "missing result file"),
        ("{not json", "invalid JSON"),
        ([1], "JSON object"),
        ({"a": {"outcome": "pass", "explanation": "x"}}, "missing criterion: b"),
        (
            {
                "a": {"outcome": "pass", "explanation": "x"},
                "b": {"outcome": "pass", "explanation": "y"},
                "c": {"outcome": "pass", "explanation": "z"},
            },
            "unexpected key: c",
        ),
        (
            {
                "a": {"outcome": "maybe", "explanation": "x"},
                "b": {"outcome": "pass", "explanation": "y"},
            },
            "a: outcome must be one of",
        ),
        (
            {
                "a": {"outcome": "pass", "explanation": "  "},
                "b": {"outcome": "pass", "explanation": "y"},
            },
            "a: explanation must be a non-empty string",
        ),
        ({"a": "pass", "b": {"outcome": "pass", "explanation": "y"}}, "a: value must be an object"),
    ],
)
def test_validator_rejects(run_validator, result, message):
    reward, stdout = run_validator(result)
    assert reward == "0"
    assert message in stdout


def test_read_result_returns_plain_json(tmp_path, monkeypatch):
    import harbor.analyze.checker as checker
    from harbor.analyze.models import QualityCheckResult
    from harbor.models.trial import result as trial_result

    from fitting_room.tasks.check import read_result

    (tmp_path / "result.json").write_text("{}")
    monkeypatch.setattr(
        trial_result.TrialResult, "model_validate_json", classmethod(lambda c, s: None)
    )
    monkeypatch.setattr(
        checker,
        "_extract_check_result",
        lambda *a: QualityCheckResult(checks={"typos": {"outcome": "pass", "explanation": "none"}}),
    )
    checks, error = read_result(tmp_path)
    assert error is None
    assert json.loads(json.dumps(checks)) == {"typos": {"outcome": "pass", "explanation": "none"}}
