# Spikes

Findings from de-risking checks (OpenSpec change `benchmark-foundation`, group 2 and task 4.1). Spike tasks live in `spikes/`; their Harbor job output goes to `results/spikes/` (gitignored). Harbor version: 0.26.0.

## 2.1 Harbor on Docker: hello world

`spikes/hello`. Ran with the built-in agents:

```sh
uv run harbor run -p spikes/hello -a oracle -o results/spikes --job-name hello-oracle -y -q
uv run harbor run -p spikes/hello -a nop    -o results/spikes --job-name hello-nop    -y -q
```

Result: oracle reward 1, nop reward 0, no `exception_info`. Harbor's local Docker backend works on this host (Docker Desktop 29.9 on WSL2).

Notes for later tasks:

- `harbor init -t` in 0.26 defaults to `[verifier] environment_mode = "separate"`. Pass `--verifier-mode shared` to get the evals-from-sessions behaviour (verifier sees the agent's final container state).
- The task schema (`harbor task schema`) has `[environment] mcp_servers` and `skills_dir`. Relevant to toolkits (task 4.6).

## 2.2 GPU passthrough and pinning

`spikes/gpu`. GPU indexes on this host: `nvidia-smi` order is 0 = RTX 3080 (`GPU-510ddc27-95ac-c62f-d49b-242cc5183c72`), 1 = RTX 3090 (`GPU-4cec666b-991c-fe31-e63f-6455bc828119`). **CUDA's default order is the reverse (fastest first: 0 = 3090).** Always pin by UUID.

Findings:

1. GPU passthrough works: containers see both GPUs and can use CUDA.
2. **Docker Desktop on WSL2 does not isolate GPUs.** `--gpus 1`, `--gpus device=0`, `--gpus device=<uuid>`, Compose `device_ids`, and `NVIDIA_VISIBLE_DEVICES` all still expose both GPUs. Harbor's `gpus = 1` in `task.toml` therefore reserves nothing on this host.
3. **`CUDA_VISIBLE_DEVICES=<uuid>` does restrict what CUDA programs see** (checked with a direct `libcuda` device count). `nvidia-smi` ignores it, so tests must check through CUDA, not `nvidia-smi`.
4. Harbor's `--extra-docker-compose <file>` adds a run-level Compose overlay without touching the task. An overlay that sets `services.main.environment.CUDA_VISIBLE_DEVICES` applies to the agent and the shared verifier.

Result through Harbor (oracle agent):

| Job | Overlay | CUDA devices seen | Reward |
|---|---|---|---|
| `gpu-unpinned` | none | 3090, 3080 | 0 |
| `gpu-pin3080` | `spikes/gpu/pin-3080.compose.yaml` | 3080 only | 1 |

**Decision:** no `DockerEnvironment` subclass is needed. `fr run` will generate a per-campaign overlay setting `CUDA_VISIBLE_DEVICES` to the task GPU's UUID. The host llama-server is pinned the same way on the host side.

**Limitation:** the pin is soft. An agent can unset `CUDA_VISIBLE_DEVICES` and reach the serving GPU. Consequences are limited to that trial (out-of-memory when allocating next to llama.cpp's preallocated weights and KV cache), but it is recorded as a known limitation of the Docker backend on WSL2. Hard isolation would need a different backend (for example, a native Linux Docker host or OpenShell with GPU support).

## 2.3 Agent-phase network allowlist

`spikes/netallow`. `task.toml` sets, for the agent phase only:

```toml
[agent]
network_mode = "allowlist"
allowed_hosts = ["pypi.org"]
```

The oracle's `solve.sh` (which runs in the agent phase) probes both hosts. Result: `github.com blocked (URLError)`, `pypi.org reachable`, reward 1, no exception. Harbor's Docker backend enforces this with its egress-control sidecar, and the required kernel netfilter support is present on this WSL2 kernel. No subclass needed.

## 2.4 Host service reachable from sandboxes

`spikes/hostsvc` (allowlist) and `spikes/hostsvc-public` (public). A test HTTP server on the host bound to **`127.0.0.1:18080` only** answered from inside the sandbox at `http://host.docker.internal:18080` in both modes:

| Job | Agent network | Host endpoint | github.com | Reward |
|---|---|---|---|---|
| `hostsvc-public` | public | reachable | reachable | 1 |
| `hostsvc-allowlist` | allowlist `["host.docker.internal"]` | reachable | blocked | 1 |

**Decision:** benchmark llama-server binds to `127.0.0.1:18080` (not exposed to the LAN). Tasks with a public upstream use `[agent] network_mode = "allowlist"` with `host.docker.internal` plus any hosted-model API hosts the run needs, which `fr run` adds per configuration.

## 4.1 Hermes headless (partial: no model call made yet)

Findings from `hermes --help` (host build `Hermes Agent v0.0.0 (2026.9.24) · upstream 951ec092`, Nix):

- **One-shot:** `hermes -z "<prompt>"` prints only the final response; tools, memory, rules and AGENTS.md in the working directory load as normal.
- **Usage:** `--usage-file PATH` (one-shot only) writes JSON with estimated cost, token counts, model and API calls, even when the run fails.
- **No prompts:** `--yolo` bypasses dangerous-command approvals; `--accept-hooks` auto-approves hooks.
- **Clean config:** `--ignore-user-config` (credentials in `.env` still load), `--ignore-rules` (skips AGENTS.md, SOUL.md, memory, preloaded skills), `--safe-mode` (also disables plugins and MCP servers).
- **Model selection:** `-m MODEL`, `--provider PROVIDER`, `--reasoning LEVEL`; toolsets via `-t`; skills via `--skills`.

**Harbor 0.26 already ships a `hermes` agent** (`harbor agent schema hermes`: `version`, `base_url`, `config`, `toolsets`, `max_turns`), and a `pi` agent usable as the base for Oh My Pi. So design D5's "new adapter" for Hermes and omp becomes "thin subclass of the built-in".

**Still to do (needs a model call, so needs the user's go-ahead):** check that Harbor's `hermes` agent installs a Hermes matching the host build (upstream `951ec092`) or needs a pinned source, and run one non-interactive prompt in a container.

**Credentials (blocker for all of group 4):** Harbor's built-in agents take API keys from the host environment (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, ...). On this machine only a GLM key exists; Codex and Claude use subscription logins. Decision pending with the user.
