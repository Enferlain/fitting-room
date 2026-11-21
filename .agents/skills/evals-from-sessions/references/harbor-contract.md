# Harbor contract (minimal)

Fitting-room pins Harbor 0.26.0 as a project dependency. Run trials through
`uv run fr run` so the job receives the Podman backend and store mounts.
Leak scans use gitleaks 8 (`gitleaks dir`).

## Task layout

```
<task-name>/
  instruction.md          # the prompt; first line = canary comment (stripped by Harbor)
  task.toml               # name, version, timeouts, resources, network, metadata
  environment/repo/       # single-commit snapshot made by fr task materialize
  tests/test.sh           # verifier entrypoint (uploaded only for verification)
  tests/verify.py         # checks + canary line; hidden fixtures next to it
  solution/solve.sh       # reference solution (uploaded only for the oracle agent)
  solution/fix.patch      # private mode: the episode diff
  provenance.md           # authoring notes; kept outside the trial
```

`harbor task init personal/<task-name> -p <tasks-dir> --no-pytest` creates the
skeleton. Remove its generated environment recipe and copy the fitting-room template over it.

## Container paths

| Path | Meaning |
|---|---|
| `/work/<repo>` | where the agent starts for repo-backed tasks |
| `/tests` | `tests/` contents, present only during verification |
| `/solution` | `solution/` contents, present only for `-a oracle` |
| `/logs/verifier/reward.txt` | `1` or `0`; a missing file is a Harbor error (`RewardFileNotFoundError`), not a `0` |
| `/logs/agent/` | agent logs, downloaded into the trial dir |

By default the verifier runs in the agent's container after the agent finishes
(`[verifier] environment_mode = "shared"`), so it sees the final files and git state.

## Canary

Harbor strips leading instruction lines that are an HTML comment or `#` comment
containing the word `canary`, so the agent never sees them. Put the same GUID in
`tests/verify.py`. The template ships one GUID; generate a new one per benchmark with
`python3 -c "import uuid; print(uuid.uuid4())"`.

## task.toml

```toml
schema_version = "1.4"   # Harbor 0.26.0

[task]
name = "personal/<task-name>"
version = "1.0.0"
description = "<one line>"

[metadata]               # free-form
source_session = "<id>"
category = "<category>"
mode = "private"         # or "shareable"
visibility = "private"
repo = "<repo>"
start_commit = "<sha>"

[verifier]
timeout_sec = 120.0

[agent]
timeout_sec = 1200.0

[environment]
docker_image = "fr-base/cpu:1"
network_mode = "public"
cpus = 2
memory_mb = 2048
storage_mb = 4096
```

## Network

`network_mode` is `public` (default), `allowlist` or `no-network`. For
tasks derived from public code, use `[agent] network_mode = "allowlist"` and
keep source-code hosts out of `allowed_hosts`. The runner adds the selected model
endpoint. Harness installs are provisioned before the trial.

## Commands

Materialize with `uv run fr task materialize <task>`. Add a local validation
campaign under `configs/campaigns/` selecting the task:

```toml
runs = ["test-oracle", "test-nop"]
repeats = 5
n_concurrent_trials = 1

[tasks]
include = ["tasks/<repo>/<task>"]
```

Run `uv run fr run <campaign>`. Expect five oracle rewards of 1.0 and five nop
rewards of 0.0. For mutants and alternative solutions, select a temp copy of the
task with a replaced `solution/solve.sh` and run one oracle attempt. Use a pinned
GLM or local run config for a real-agent smoke.

Run the directory leak probe before starting the smoke:

```sh
<skill>/assets/leak-probe.sh <task> <validation-dir>/solution-strings.txt
```

## Reading results

```
results/<campaign>/<timestamp>/<run>/
  result.json                     # job summary
  <task>__<id>/result.json        # verifier_result.rewards.reward, exception_info, agent_result (tokens, cost_usd)
  <task>__<id>/verifier/reward.txt
  <task>__<id>/verifier/test-stdout.txt   # your PASS/FAIL lines
  <task>__<id>/agent/             # agent logs (pi.txt for Pi, oracle.txt for oracle)
  <task>__<id>/trial.log          # build/setup/infrastructure errors
```

```bash
cat results/<campaign>/<timestamp>/<run>/*/verifier/reward.txt
python3 -c "import json,glob; [print(f, json.load(open(f)).get('exception_info')) for f in glob.glob('results/<campaign>/<timestamp>/<run>/*/result.json')]"
```

A non-null `exception_info` means an infrastructure or timeout failure, not a model
failure. The smoke run must have none.
