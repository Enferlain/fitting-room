# Running benchmarks

A **campaign** runs a set of tasks under one or more **run configurations**, several times each, through [Harbor](https://docs.harborframework.com) on the local Docker backend. Results stay local under `results/` (gitignored).

```sh
uv run fr run <campaign>
```

`fr run` validates the campaign and every run configuration it names before anything starts, and lists every problem it finds at once. It then runs one Harbor job per configuration and prints a pass / fail / infrastructure-error count for each.

## Try it: free smoke campaign

This uses Harbor's built-in test agents (`oracle` applies the reference solution, `nop` does nothing), so it costs nothing and needs no API keys:

```sh
uv run fr run smoke-hello
```

Expected output (paths differ):

```text
test-oracle: 3 passed, 0 failed, 0 infrastructure errors (pass rate 100%) -> results/smoke-hello/<stamp>/test-oracle
test-nop: 0 passed, 3 failed, 0 infrastructure errors (pass rate 0%) -> results/smoke-hello/<stamp>/test-nop
```

## Run configuration: `configs/runs/<name>.toml`

One harness × model × arm × toolkit (× serving profile) combination. The file name is the configuration's name.

```toml
harness = "codex"              # codex | claude-code | opencode | hermes | omp
harness_version = "0.162.0"    # required: the exact version installed in the sandbox
model = "zai/glm-5.3"          # required: '<provider>/<model id>' (zai or local)
effort = "medium"              # required: reasoning effort, passed explicitly
arm = "stock"                  # optional, default "stock": configs/arms/<arm>/
toolkit = "none"               # optional, default "none": configs/toolkits/<toolkit>/
# serving_profile = "qwen-coder-3090"  # required for local models: configs/serving/<name>.yaml
```

Rejected before any trial starts:

- missing `harness_version`, `model` or `effort` (for real harnesses);
- a `local/...` model without `serving_profile`, or a `serving_profile` on a hosted model;
- an `arm`, `toolkit` or `serving_profile` with no matching directory or file;
- an unknown harness or an unknown field (typos are errors, not ignored);
- a harness whose adapter is not implemented yet.

`harness = "oracle"` and `harness = "nop"` are test-only and need nothing else (see `configs/runs/test-*.toml`).

## Models and providers

The provider is the part of `model` before the slash. Benchmarked models are GLM and local models (GPT and Claude models are not benchmarked).

| Provider | Example `model` | How it connects |
|---|---|---|
| `zai` | `zai/glm-5.3`, `zai/glm-5.3-flash` | z.ai's Anthropic-compatible endpoint with the placeholder key `av-managed-key`. The host's Agent Vault substitutes the real key in-flight; `fr run` mounts Agent Vault's public CA into the sandbox through a generated Compose overlay. Agent Vault must be unlocked. |
| `local` | `local/qwen3.5-9b` | The serving profile's endpoint at `host.docker.internal:18080` with a placeholder key. Start it first with `uv run fr serve up <profile>`; `fr run` refuses local runs when it is down. |

Only harness × provider pairs that have passed a smoke run are accepted (see `docs/harnesses.md`); others are refused before anything starts. Currently: `claude-code` × `zai`, `opencode` × `local`.

```sh
uv run fr serve up qwen35-9b-3080   # only needed for local models
uv run fr run smoke-real            # one hello trial per supported pair
uv run fr serve down qwen35-9b-3080
```

## Campaign: `configs/campaigns/<name>.toml`

```toml
runs = ["codex-medium", "claude-code-medium"]   # run configuration names
repeats = 3                                     # trials per task per configuration (default 3)

[tasks]
include = ["tasks/sd-scripts/*", "tasks/hcom/*"]  # globs, relative to the repo root
exclude = ["tasks/hcom/flaky-*"]                  # optional globs to drop
repos = ["sd-scripts"]                            # optional: task.toml [metadata] repo
tracks = ["coding"]                               # optional: coding | investigative

[gpu]                                             # optional; see local model serving
serving_gpu = "GPU-4cec666b-991c-fe31-e63f-6455bc828119"   # RTX 3090
task_gpu    = "GPU-510ddc27-95ac-c62f-d49b-242cc5183c72"   # RTX 3080
```

A directory counts as a task when it contains `task.toml`. A campaign whose selection matches no tasks is rejected.

## Results layout

```text
results/<campaign>/<YYYYmmdd-HHMMSS>/
  <run name>/                 # one Harbor job per run configuration
    job-config.json           # the exact Harbor JobConfig used
    result.json, job.log      # Harbor job summary
    <task>__<id>/             # one directory per trial
      result.json             # Harbor: rewards, timings, agent usage, exception_info
      fitting_room.json       # resolved run config, arm/toolkit/serving digests, task version
      agent/ verifier/ trial.log
```

## Outcomes

Each trial is **pass**, **fail** or **infrastructure error**:

- An exception that leaves no valid reward (image build, sandbox start, endpoint unreachable, auth, rate limit and similar) is an infrastructure error. It is excluded from pass rate and counted separately.
- Agent timeouts, context-window overflows and non-zero agent exits are model failures: the verifier still grades the final state.
- Exception types Harbor does not recognise are treated as infrastructure errors, so an adapter bug is never scored as a model failure.
- A trial with no reward at all is an infrastructure error.
