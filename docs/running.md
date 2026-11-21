# Running benchmarks

A **campaign** runs a set of tasks under one or more **run configurations**, several times each, through [Harbor](https://docs.harborframework.com) in rootless Podman on WSL. Results stay local under `results/` (gitignored).

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
harness = "claude-code"              # codex | claude-code | opencode | hermes | omp
harness_version = "2.1.263"    # required: the exact version installed in the sandbox
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
| `local` | `local/qwen3.5-9b` | The serving profile's endpoint at `host.containers.internal:18080` with a placeholder key. Start it first with `uv run fr serve up <profile>`; `fr run` refuses local runs when it is down. |

Only harness × provider pairs that have passed a smoke run are accepted (see `docs/harnesses.md`); others are refused before anything starts. Currently, Claude Code and Oh My Pi use z.ai, Codex and OpenCode use the local endpoint, and Hermes supports both.

```sh
uv run fr serve up qwen35-9b-3080   # only needed for local models
uv run fr run smoke-real            # one hello trial per supported pair
uv run fr serve down qwen35-9b-3080
```

## Campaign: `configs/campaigns/<name>.toml`

```toml
runs = ["codex-medium", "claude-code-medium"]   # run configuration names
repeats = 3                                     # trials per task per configuration (default 3)
n_concurrent_trials = 1                        # serialize trials (default 4; GLM runs are capped at 2)
agent_timeout_multiplier = 2.0                  # optional: double the task's agent budget

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

The optional `agent_timeout_multiplier` scales each task's `[agent] timeout_sec`.
For a smoke task with a 600-second timeout, `2.0` allows 20 minutes for agent
execution. The multiplier is saved in the generated `job-config.json`. Setup
and verifier timeouts use their existing settings.

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

- An exception that leaves no valid reward (sandbox start, endpoint unreachable, auth, rate limit and similar) is an infrastructure error. It is excluded from pass rate and counted separately.
- Agent timeouts, context-window overflows and non-zero agent exits are model failures: the verifier still grades the final state.
- Exception types Harbor does not recognise are treated as infrastructure errors, so an adapter bug is never scored as a model failure.
- A trial with no reward at all is an infrastructure error.

## Podman setup (one time)

Enable rootless Podman in the WSL distro. On NixOS, enable
`virtualisation.podman.enable` with `dockerCompat = false`. Configure pasta
for loopback access in `~/.config/containers/containers.conf` if the trials
need to reach a model or probe on the host:

```toml
[network]
pasta_options = ["--map-host-loopback", "169.254.1.2"]
```

```sh
podman build -t localhost/fr-base/cpu:1 images/base-cpu
fr_store=${FR_STORE:-$HOME/.local/share/fitting-room/store}
mkdir -p "$fr_store/tools"
nix build nixpkgs#docker-compose -o "$fr_store/tools/docker-compose"
uv run fr doctor
```

`fr run` uses Compose V2 over the Podman socket with Windows executables removed from its
PATH. Set `FR_PODMAN_COMPOSE_PROVIDER` to select another Linux Compose V2 binary.
Set `FR_STORE` to override `~/.local/share/fitting-room/store`. Keep the store, uv cache,
Podman graph root, tasks and results on the WSL filesystem. The uv cache and store must
share a filesystem for hardlinks.

Each repo uses the canonical environment in `configs/repos/<repo>.toml`. `fr run`
provisions missing environments and pinned harnesses before starting Harbor. To
prepare or inspect these inputs separately:

```sh
uv run fr env ensure <repo>
uv run fr env check tasks/<repo>/<slug>
uv run fr harness ensure <name> <version>
uv run fr store gc
```

`fr env check` reports historical lock differences. `fr store gc` previews unused
environments, harnesses and toolkits. Add `--apply` to remove the listed entries.

## Materializing a task's repo snapshot

Declare the shared image in `task.toml`:

```toml
[environment]
docker_image = "fr-base/cpu:1"
```

```sh
uv run fr task materialize tasks/<repo>/<slug>
```

The command uses `[metadata] repo` and `start_commit` to archive the local source
commit from `~/Projects/<repo>` (override the parent with `FR_REPOS_DIR`). It strips
credential files, outward symlinks and Beads connection state, then creates one fresh
Git commit without remotes, hooks or reflogs. The snapshot is gitignored and the
materialization record stays in `environment/.materialized.json`. Submodules are
reported and their contents are omitted. Each trial copies the snapshot into
`/work/<repo>` and mounts the canonical dependencies read-only.

Per-repo excludes live in `configs/repos/<repo>.toml` (`exclude` = glob patterns on
repo-relative paths). pytortch-backend-experiments drops its generated stage artifacts
(17,789 of 21,448 files at `0ad1b254`), which flood git, ripgrep and codebase-memory. A
task that needs some of them lists them under `[metadata] snapshot_include`; both are
recorded in `environment/.materialized.json`.

## Sequential acceptance campaign

`podman-acceptance` runs three oracle repeats per available task and spike. It
uses the dev-stack toolkit for the toolkit smoke, and pins the task GPU to the
local RTX 3080. Update its UUID for a different host. Materialize each repo-backed
task first, including `spikes/toolkit-check` and `spikes/sd-rust-check`. For a
zero-build measurement, start with the shared base and the Harbor egress sidecar
already present. Harbor prepares the sidecar when it first runs an allowlisted trial.

The two host-service spikes need a fixture on the same loopback port used by the
benchmark model endpoint. With that port free, serve a file named `ping` containing
`fitting-room-pong` from a temporary directory using
`python3 -m http.server 18080 --bind 127.0.0.1 --directory <fixture-dir>`. Then run
`uv run fr run podman-acceptance` and stop the fixture server after the campaign.
