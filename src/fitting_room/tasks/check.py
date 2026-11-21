"""`fr task check`: Harbor's task quality checker run through fitting-room (bead 2do).

`harbor check` wraps the task under review in a reviewer task and runs it with its own
environment and agent settings, which bypasses the Podman subclass, the harness store
and Agent Vault. Here the wrapper is assembled with Harbor's own code (same prompt,
rubric and result schema), adapted to the shared Podman base, and run as a one-trial
campaign through `run_campaign` with a fitting-room run configuration.

Adaptations, all recorded in the reviewer's instruction:
- the repo snapshot (`environment/repo/`) is left out of the review copy: it is the
  source repo at the start commit, can hold thousands of files, and Harbor's prompt
  asks the reviewer to read every file;
- the base image has no Python, so the result is validated with jq;
- the agent phase uses the allowlist with no extra hosts (`fr run` adds the model).
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from fitting_room.podman_host import BASE_IMAGE

RESULT_FILENAME = "check-result.json"
OMITTED = ("environment/repo",)

WRAPPER_TOML = f"""\
schema_version = "1.4"
artifacts = [{{ source = "/app/{RESULT_FILENAME}", destination = "{RESULT_FILENAME}" }}]

[metadata]
fr_task_check = true

[agent]
timeout_sec = 1800.0
network_mode = "allowlist"
allowed_hosts = []

[verifier]
timeout_sec = 120.0
environment_mode = "shared"

[environment]
docker_image = "{BASE_IMAGE}"
workdir = "/app"
network_mode = "public"
cpus = 1
memory_mb = 2048
"""

# Same checks as Harbor's validate.py (keys match the rubric, outcome enum, non-empty
# explanation), in jq because the shared base image has no Python.
TEST_SH = r"""#!/bin/bash
# fitting-room port of Harbor's check validator (no Python in the shared base image).
mkdir -p /logs/verifier
reward=0
trap 'echo "$reward" > /logs/verifier/reward.txt' EXIT
result=/app/check-result.json
if [ ! -f "$result" ]; then echo "missing result file: $result"; exit 0; fi
if ! jq -e . "$result" >/dev/null 2>&1; then echo "invalid JSON"; exit 0; fi
jq -r --slurpfile c /tests/criteria.json '
  if type != "object" then "result must be a JSON object keyed by criterion name"
  else
    ($c[0] - keys | map("missing criterion: " + .))[],
    (keys - $c[0] | map("unexpected key: " + .))[],
    (to_entries[] | select(.key | IN($c[0][])) |
      if (.value | type) != "object" then "\(.key): value must be an object"
      else
        (if (.value.outcome | IN("pass", "fail", "not_applicable")) then empty
         else "\(.key): outcome must be one of [\"fail\", \"not_applicable\", \"pass\"]" end),
        (if (.value.explanation | type) == "string" and (.value.explanation | test("\\S"))
         then empty else "\(.key): explanation must be a non-empty string" end)
      end)
  end' "$result" > /tmp/check-errors.txt
if [ -s /tmp/check-errors.txt ]; then cat /tmp/check-errors.txt; exit 0; fi
reward=1
"""


class CheckError(Exception):
    pass


def _context_note(task_dir: Path) -> str:
    cfg = tomllib.loads((task_dir / "task.toml").read_text())
    meta = cfg.get("metadata", {})
    repo = meta.get("repo")
    if repo is None:
        return ""
    snapshot = task_dir / "environment" / "repo"
    files = sum(1 for p in snapshot.rglob("*") if p.is_file() and ".git" not in p.parts)
    commit = meta.get("start_commit", "the recorded start commit")
    return f"""
# fitting-room context

This task runs on fitting-room's trial setup, not on a per-task Dockerfile:
- `environment/repo/` is omitted from the copy you are reviewing. It is a snapshot of the
  `{repo}` repository at {commit} ({files} files), made by `fr task materialize` as one fresh
  commit with no later history. Nothing else is in the agent's environment.
- Every trial starts from one shared base image. The snapshot is copied to `/work/{repo}`,
  which is the agent's working directory. The repo's pinned dependencies come from a canonical
  environment mounted read-only (`$VIRTUAL_ENV`); the verifier uses that interpreter.
- `tests/` and `solution/` are never in the agent's environment; Harbor uploads `tests/` only
  for the verifier phase.
Judge the criteria with this setup in mind.
"""


def assemble(task_dir: Path, dest: Path, rubric_path: Path | None = None) -> Path:
    """Build the reviewer task for ``task_dir`` at ``dest`` and return its path."""
    from harbor.analyze.checker import CHECK_TASK_TEMPLATE_DIR, PROMPTS_DIR, assemble_check_task
    from harbor.analyze.models import build_check_response_model, load_rubric

    task_dir = task_dir.resolve()
    if not (task_dir / "task.toml").is_file():
        raise CheckError(f"{task_dir} is not a task directory (no task.toml)")
    if not (task_dir / "instruction.md").is_file() or not (task_dir / "tests").is_dir():
        raise CheckError(f"{task_dir} needs instruction.md and tests/ to be checked")
    del CHECK_TASK_TEMPLATE_DIR  # Harbor reads it; imported to fail early if it moves.

    rubric = load_rubric(rubric_path)
    schema = build_check_response_model(rubric).model_json_schema()
    dest.mkdir(parents=True, exist_ok=False)
    review = dest / "review-copy"

    def ignore(src: str, names: list[str]) -> set[str]:
        rel = Path(src).resolve().relative_to(task_dir)
        skip = {n for n in names if (rel / n).as_posix() in OMITTED}
        return skip | {n for n in names if n in (".git", "__pycache__")}

    shutil.copytree(task_dir, review, ignore=ignore)
    wrapper = assemble_check_task(
        task_dir=review,
        rubric=rubric,
        template=(PROMPTS_DIR / "check.txt").read_text(),
        output_schema=schema,
        dest=dest / f"check-{task_dir.name}",
    )
    shutil.rmtree(review)
    (wrapper / "task.toml").write_text(WRAPPER_TOML)
    test_sh = wrapper / "tests" / "test.sh"
    test_sh.write_text(TEST_SH)
    test_sh.chmod(0o755)
    (wrapper / "tests" / "validate.py").unlink()
    instruction = wrapper / "instruction.md"
    instruction.write_text(instruction.read_text().rstrip() + "\n" + _context_note(task_dir))
    return wrapper


@dataclass
class CheckOutcome:
    task: str
    checks: dict | None
    error: str | None
    trial_dir: Path | None
    report_path: Path


def read_result(trial_dir: Path, rubric_path: Path | None = None) -> tuple[dict | None, str | None]:
    """Parse a finished reviewer trial with Harbor's own result extraction."""
    from harbor.analyze.checker import _extract_check_result
    from harbor.analyze.models import build_check_response_model, load_rubric
    from harbor.models.trial.result import TrialResult

    model = build_check_response_model(load_rubric(rubric_path))
    trial = TrialResult.model_validate_json((trial_dir / "result.json").read_text())
    try:
        result = _extract_check_result(trial, trial_dir, model)
    except (ValueError, RuntimeError) as err:
        return None, str(err)
    return result.model_dump(mode="json")["checks"], None


def check_task(
    task_dir: Path,
    run_name: str,
    repo_root: Path,
    *,
    rubric_path: Path | None = None,
    results: Path = Path("results"),
    now: dt.datetime | None = None,
) -> CheckOutcome:
    """Assemble the reviewer task, run it once with ``run_name``, and report."""
    from fitting_room.config import (
        Campaign,
        CampaignConfig,
        ConfigRoot,
        TaskSelector,
        load_run,
    )
    from fitting_room.runner import run_campaign, trial_dirs

    stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    work = repo_root / "work" / "task-checks" / task_dir.resolve().name / stamp
    wrapper = assemble(task_dir, work, rubric_path)
    root = ConfigRoot(repo_root / "configs")
    run = load_run(run_name, root)
    campaign = Campaign(
        config=CampaignConfig(
            name="task-check",
            runs=[run_name],
            repeats=1,
            n_concurrent_trials=1,
            tasks=TaskSelector(include=[str(wrapper)]),
        ),
        runs=[run],
        task_dirs=[wrapper],
    )
    (job,) = run_campaign(campaign, repo_root / results, root, now=now)
    trials = trial_dirs(job.job_dir)
    if len(trials) != 1:
        checks, error, trial = (
            None,
            f"expected one trial in {job.job_dir}, found {len(trials)}",
            None,
        )
    else:
        trial = trials[0]
        checks, error = read_result(trial, rubric_path)
    report = {
        "task": str(task_dir),
        "run": run_name,
        "trial_dir": str(trial) if trial else None,
        "omitted": list(OMITTED),
        "checks": checks,
        "error": error,
    }
    report_path = job.job_dir / "check_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return CheckOutcome(task_dir.name, checks, error, trial, report_path)
