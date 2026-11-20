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

## 4.1 Hermes headless

Host build: `Hermes Agent v0.0.0 (2026.9.24) · upstream 27e38935` (Nix). Upstream's newest release tag `v2026.9.24` is commit `f97608f178d1ffeca59860195ab7da295f7c8e5f`.

CLI (`hermes chat --help`): one-shot `-q` / `-z`, `--yolo` (no approvals), `--reasoning LEVEL`, `--provider`, `--ignore-user-config`, `--ignore-rules`, `--safe-mode`, `--usage-file`.

**Harbor 0.26's built-in `hermes` agent does most of the work:** one-shot `hermes --yolo chat -q`, a fresh `HERMES_HOME=/tmp/hermes` (no host config, memory and user profile off, checkpoints off), `hermes sessions export` to ATIF, MCP servers and skills through Hermes's own config. GLM goes through Hermes's native `zai` provider (`GLM_API_KEY`); local models through its `openai-api` provider (`OPENAI_BASE_URL`).

Gaps fixed in `fitting_room.adapters.hermes:FrHermes` (verified 2026-11-17, Hermes + local Qwen3.5-9B on `spikes/hello`: reward 1, ATIF written, 10,644 in / 10,513 cached / 68 out tokens):

| Gap | Fix |
|---|---|
| Harbor pins with `--branch`; the installer needs `--commit` for a SHA | install with `--commit <sha>` |
| The installer on `main` expects main's repo layout (`pm/`), so pinned installs fail | fetch `install.sh` from the pinned commit |
| Install took 14 min in a plain container and hit Harbor's 20 min setup timeout in a trial; Playwright, Chromium and fonts were most of it | `--skip-browser --skip-computer-use`: ~6 min. Browser tools can't reach anything on the allowlisted network anyway. |
| `hermes version` doesn't exist in this release | version check uses `hermes --version` |
| No reasoning level is ever set | `reasoning_effort` option (no `none`) into `agent.reasoning_effort` and `--reasoning` |
| Hermes rejects keys that look like placeholders (`placeholder`, `dummy`, `sk-…`) | local provider key is `no-key-required` (Hermes's documented no-auth value) |
| Token counts are summed from per-message usage, empty for llama.cpp | fall back to the session export's totals |

Notes:
- Six minutes of install per trial is still slow. If campaigns get long, bake Hermes into a cached image layer.
- Hermes detects WSL from the kernel and tells the model the Windows drives are under `/mnt/c`. They aren't mounted in the sandbox; the model may waste a call looking. Same kernel string for every harness, so not a fairness issue, but it is noise.
- The bundled skill list (58 skills) is in Hermes's system prompt by default. That is stock Hermes; toolkits (task 4.6) decide what else is added.
- GLM through Hermes passed the hello task on 2026-11-18 (see docs/harnesses.md).

## Podman (change `podman-trial-environments`, tasks 1–2), 2026-11-20

Podman 5.8.9 rootless (NixOS `virtualisation.podman`), storage `~/.local/share/containers/storage` on the NixOS disk (`D:\WSL\NixOS`). Base image `localhost/fr-base/cpu:1` built with `podman build images/base-cpu`: 704 MB, 72 s.

| Check | Result |
|---|---|
| hello task, oracle / nop (2.1) | 1 / 0 |
| `label-busy-port` with `docker_image = localhost/fr-base/cpu:1` (no build), snapshot copied in, data-processing shared env mounted read-only (2.3) | oracle 1, nop 0 (fails on the real bug); snapshot checksum unchanged; trial 25 s (environment setup 2.5–6.6 s, verifier 7.5 s); no containers, networks or volumes left |
| egress allowlist, `spikes/netallow` (2.5) | `github.com` blocked, `pypi.org` reachable, reward 1 |
| GPU (2.6), `spikes/gpu` with `gpus = 0` + overlay (`devices: [/dev/dxg]`, `/usr/lib/wsl:ro`, `LD_LIBRARY_PATH`, `CUDA_VISIBLE_DEVICES=<3080 UUID>`) | CUDA sees exactly one device, the RTX 3080; reward 1 |
| data-processing shared env (`uv venv --relocatable` + `uv sync --frozen --no-install-project`, `UV_LINK_MODE=hardlink`) | 9 s including the interpreter download; 3,217 of 3,292 files hardlinked into `~/.cache/uv`; entry-point scripts relocatable, so the env mounts at `/opt/venv` |

What had to change, and why:

1. **PATH without `/mnt/*` for every Podman call.** Each `podman` invocation probes PATH for about ten OCI runtimes; with WSL's appended Windows PATH (about 40 entries on `/mnt/c`) that took ~1 s per call (`podman version` 971 ms → 38 ms with a clean PATH). Harbor makes many calls per phase, so this was most of the 90–130 s per trivial trial.
2. **Compose frontend: `podman compose` with docker-compose as provider**, over the Podman socket (`podman.socket` is enabled). podman-compose 1.5 lacks `cp` and `exec --no-TTY`, which Harbor's egress sidecar needs. The user's global `PODMAN_COMPOSE_PROVIDER` (podman-compose, set to keep Docker Desktop's compose away) stays; fitting-room sets the provider only for its own Harbor runs, using nixpkgs' docker-compose (unrelated to Docker Desktop).
3. **`environment.delete = false`.** With delete on, Harbor runs `compose down --rmi local`, which through Podman removed the shared prebuilt base image after the first trial. Plain `down` still removes containers and networks.
4. **`init: true` on the main service.** `sleep infinity` as PID 1 ignores SIGTERM, so every `down` waited the 10 s stop timeout.
5. **`:O` (copy-on-write) bind mounts do not survive the compose → Podman API path.** They became plain read-write binds: the oracle wrote its fix into the host snapshot, and the following nop trial scored 1 on the fixed code (files on the host ended up owned by a container UID; removed with `podman unshare rm -rf`). Plain `:O` works with `podman run`, not through compose. **Decision:** mount the snapshot read-only at `/opt/fr-snapshot` and copy it into the container's writable layer at start (`cp -a`, about 11 MB here, 110 MB for pytortch). Read-only binds are honoured (writes to the snapshot and the env fail with "Read-only file system").

**2.4, real harness:** Claude Code 2.1.263 + GLM 5.3 Flash (effort high) through Agent Vault on `label-busy-port`: reward 1 (all three checks pass), environment setup 3 s, agent setup (per-trial Claude Code install) 21 s, agent 603 s (hit the 600 s agent timeout after the fix was in; 1.29 M input / 15.7 k output tokens), verifier 9 s. The agent's first `uv run python` failed: uv tried to build and install the project itself (`hatchling` from PyPI), and the task's allowlist blocks PyPI. The agent switched to `PYTHONPATH=/work/data-processing/src /opt/venv/bin/python -m pytest`. Decision for design P4: option (b), i.e. `UV_NO_SYNC=1` in the container plus a generated `.pth` (and console scripts) for the project's own source, so `uv run` works against the read-only env without network.


### Sections 3–4 integration checks

- The canonical config for sd-scripts pins `38cdc295ee` and Python 3.14.5t. `fr env check` reports 99 differing package-name/version sets for `responsive-ctrl-c` and an old interpreter constraint of `>=3.11, <3.14`. The unchanged signal-delivery verifier rejected the original snapshot and accepted its reference patch on Python 3.14.5t inside the offline Podman base image. Both private drafts now use the prebuilt image and select Python through `VIRTUAL_ENV`. Under `fr run`, the interrupt task scored 1 in five oracle trials and 0 in five no-op trials, without infrastructure errors.
- `fr run` ran `label-busy-port` with oracle and nop (rewards 1 / 0, zero infrastructure errors). A separate live probe used `uv run catalog --help` offline against the read-only venv, rejected writes to both the venv and snapshot mounts, and used the CUDA driver to confirm exactly one visible RTX 3080. The WSL driver mount needed Compose's short bind syntax.
- The initial sd-scripts provisioning downloaded missing packages and built free-threaded OpenCV and grpcio. A fresh offline recreation hardlinked 30,484 of 30,973 files into the uv cache. Its apparent size was 7.32 GB and it used 19.3 MB of additional disk, excluding the managed interpreter. OpenCV, grpcio and PyTorch imported in the Podman base image.
- hcom's Debian 1.97.1 toolchain warmed the registry and target once. Two Podman trials reused that seed and each completed `cargo test --workspace --locked --offline --no-run` in under a second of Cargo time, with no crate recompilations.
- `fr doctor` reported the local rootless graph root, store, tasks and results on WSL and refused `FR_STORE=/mnt/c/fr-store`.
- The pytortch warm step compiled both Rust targets using the managed interpreter for source fingerprinting. Runtime verification used the linked sd-scripts venv through `stage0/.venv`, without Triton. The first GPU attempt exposed a missing `nvidia-smi` on PATH. The GPU overlay now exposes the WSL driver tools with the driver libraries.
- The Tracel LLVM bundler installs an SDK independently of Cargo. The warmed SDK now mounts read-only at the same XDG data path in trials. A network-disabled Podman trial rebuilt the bridge using that seed, created the isolated venv and imported PyTorch.
- The CubeCL subset on the RTX 3080 matched the prior baseline: 626 passed and 9 skipped after deselecting the seven retired Stage 5 equivalence cases. The serial prefix had 303 passes and nine skips. The remaining 323 test IDs passed in a four-worker trial on the final seed with network disabled. A separate focused run on the final seed also passed 16 earlier cases.
