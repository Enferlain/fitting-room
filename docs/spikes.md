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

### sd-scripts composite environment (2026-11-20)

`configs/repos/sd-scripts.toml`: `kind = "python+rust"`, `rust = "1.99.1"`, `rust_manifests = [pliron_candidate/native/Cargo.toml]`. `fr env ensure sd-scripts` reused the existing Python venv (same key) and warmed the Rust half in 42 s (toolchain, `cargo fetch --locked`, `cargo test --no-run` into the shared target). `spikes/sd-rust-check` at N7's commit (`5a737c27`), agent network allowlist empty: `cargo test --locked --offline` on the Pliron crate passes and the venv imports torch 2.14.1+cu130 and xdsl; oracle 1, trial 31 s (`configs/campaigns/spike-sd-rust.toml`).

### Podman section 5: harness and toolkit stores (2026-11-20)

`fr harness ensure <name> <version>` used the prebuilt Debian base to install npm
prefixes for Codex, Claude Code and OpenCode, the standalone release binary for
Oh My Pi, and the uv-locked Hermes CLI environment at the pinned SHA. All five
binaries reported the expected versions in separate read-only, network-disabled
Podman containers. The Hermes check paired its release banner with the full
checkout SHA. A fresh Oh My Pi install verified the published release checksum
and completed in 5.2 s. `dev-stack` similarly verified bd 1.3.2 and OpenSpec
1.15.0 offline. A fixture confirmed that store GC keeps the referenced toolkit
digest and removes obsolete managed installs.

Warm Harbor trial times from environment setup start to agent execution start:

| Harness | Smoke task | Startup | Reward |
|---|---|---:|---:|
| Codex 0.163.0 + Qwen3.5-9B | `hello` | 1.79 s | 1 |
| Claude Code 2.1.263 + GLM 5.3 Flash | `toolkit-check` | 7.63 s | 1 |
| Oh My Pi 18.12.6 + GLM 5.3 Flash | `toolkit-check` | 7.71 s | 1 |
| Hermes 2026.9.24 + GLM 5.3 Flash | `toolkit-check` | 7.78 s | 1 |
| OpenCode 2.2.6 + Qwen3.5-9B | `toolkit-check` | 9.37 s | 1 |

The optional Codex toolkit run caught Debian's login shell resetting `PATH`. A
trial-local profile now restores the same path as the Compose environment.
Codex's rerun on the toolkit task scored 1 and started in 7.60 s. The optional
Hermes + Qwen3.5-9B run used both tools but scored 0 because it listed changes
instead of specs. The oracle and all three GLM toolkit runs passed both checks.
With `toolkit = "none"`, Claude Code could see neither tool and scored 0.
Local logs are under `work/podman-section-5/results/`.

To recreate the toolkit snapshot on a fresh checkout:

```sh
uv run fr task materialize spikes/toolkit-check
uv run fr run smoke-toolkit-glm
```

### Podman section 6 acceptance (2026-11-20)

`podman-acceptance` ran nine tasks and spikes three times each with the oracle
and dev-stack on the warm store. All 27 trials scored 1 with zero infrastructure
errors in 5m 17s. Harbor trial timestamps confirmed the runs did not overlap.
The GPU spike saw only the RTX 3080. The allowlist denied GitHub and reached PyPI
on all three attempts. Both host-service variants reached the loopback fixture.

| Allocated bytes | Before | After | Delta |
|---|---:|---:|---:|
| Benchmark store | 12,101,500,928 | 12,101,500,928 | 0 |
| Podman graph root | 1,514,962,944 | 1,514,962,944 | 0 |

The image inventory was identical. Podman logged one Alpine pull and no image
builds. Docker Desktop reported no `fr-*` image tags. The run and its
before/after inventories are under `work/podman-section-6/` with job stamp
`20261120-203109`.

Earlier passes caught inherited sd-scripts Dolt server metadata and an intermittent
PyPI timeout. The materializer now retains the JSONL issue seed and strips
connection state. The network probe now checks HTTPS response headers and retries
the allowed endpoint within a fixed limit. The failed attempts remain in the logs.

Separately, the two private drafts each passed 5/5 oracle trials and scored zero
in all five no-op trials without infrastructure errors. Their directory probes
found exactly one Git commit and no hooks, remotes, reflogs, unreachable objects,
or reference-string hits.

### Seeds without the repos' own crates (review, 2026-11-21)

The warmed Rust targets held each repo's own crates compiled at the canonical commit (newer than most snapshots), which the directory leak probe never sees. Native recipe 2 removes every workspace member's artifacts after warming (`cargo metadata --no-deps` → `cargo clean -p`, dev and release). Remaining own-crate artifacts: sd-scripts 0 (198 dependency artifacts kept), hcom 0, pytortch 0 (`target` and `bridge-target`). Offline trial checks at the canonical commits: `spikes/sd-rust-check` passes (verifier 7 s); hcom `cargo test --workspace --locked --offline --no-run` passes in 36 s; pytortch trial setup (`build.sh`) completes in 92 s and produces the native `.so`. Re-provisioning took 37 s (sd-scripts), 77 s (hcom) and 451 s (pytortch).

### Public web research on Podman (2026-11-21)

`uv run fr run smoke-web-research` exercises public HTTPS on a standalone
research task. The oracle and Claude Code 2.1.263 with GLM 5.3 Flash scored 1.
The no-op scored 0. All three trials completed without infrastructure errors.
The Claude Code trajectory recorded Bash calls that fetched and read the
[RFC 9116 text](https://www.rfc-editor.org/rfc/rfc9116.txt) before writing the
answer. Local results are under
`work/bead-2le/smoke-web-research/20261121-035554/`.

Public-upstream coding tasks retain agent-phase allowlists. The Section 6
`netallow` trial tested the restricted path, and Section 5's toolkit smoke
tested opt-in Beads and OpenSpec with a seeded, trial-local issue database.

### GLM effort wire capture (2026-11-21)

The probe ran the pinned binaries from the harness store with fresh client
state and the same short modular arithmetic question. A local HTTP relay
forwarded model calls to the actual Z.AI coding endpoints through Agent Vault.
It recorded selected request fields, status, usage and the length of exposed
thinking text. It rejected requests for other models and any explicit
thinking-off request. Native run configurations are unchanged apart from the
Hermes title fix described below. This was a CLI wire probe, separate from
the Podman task campaign. The probe and sanitized wire log are under
`work/bead-os6/`.

The OpenAI-compatible endpoint reported `completion_tokens_details.reasoning_tokens`.
The Messages endpoint exposed thinking text but omitted a reasoning-token
breakdown in these captures. Output tokens there include the broader output
and cannot be compared directly with reasoning tokens. The question and model
were held fixed for each series. Harness system prompts can differ, so the
results qualify the wire mappings and observed usage for this question.

In the Hermes pilot, the auxiliary session-title request sent thinking disabled
and the relay rejected it. The adapter now keeps the locally derived title and
disables the model upgrade. The main request still uses the configured effort.
`smoke-hermes-glm` passed in Podman with zero infrastructure errors after the
change, and the session export contained the locally derived title. The run
is under `work/bead-os6/hermes-smoke/`.

OpenCode's GLM probe used an explicit OpenAI-compatible provider with
configured variants. With Flash, the `low`, `medium`, `high`, and `max`
variants each sent `thinking.type = "enabled"` and the configured
`reasoning_effort` on the main request. The single runs returned 295, 115,
691, and 889 reasoning tokens respectively. The supported `fr run` pairing
for OpenCode remains local models.

**GLM 5.3 spot checks.** Each cell below is one successful main request unless it
lists multiple CLI settings. These checks isolate transport and field changes
between GLM 5.3 and Flash.

| Harness | CLI effort | Endpoint | Thinking | Sent effort | Reasoning returned |
|---|---|---|---|---|---|
| Claude Code | medium | Messages | adaptive | medium | 176 characters |
| Oh My Pi | low, medium | Messages | enabled, budget 2,048 | low | 1,373 / 130 characters |
| Oh My Pi | high | Messages | enabled, budget 16,384 | high | 1,696 characters |
| Oh My Pi | max | Messages | enabled, budget 32,768 | max | 1,544 characters |
| Hermes | medium | Chat Completions | enabled | medium | 534 tokens |
| OpenCode, custom provider | medium | Chat Completions | enabled | medium | 947 tokens |

**GLM 5.3 Flash, five runs per distinct main-request setting in the
configured harnesses.** Ranges show the minimum and maximum, with the median
in parentheses. The OpenCode custom route and duplicate labels are spot checks
listed separately.

| Harness | CLI effort | Sent effort | Reasoning returned |
|---|---|---|---|
| Claude Code | low | low | 432–1,207 characters (561) |
| Claude Code | medium | medium | 456–819 characters (606) |
| Claude Code | high | high | 1,013–1,230 characters (1,161) |
| Claude Code | xhigh | xhigh | 776–1,888 characters (926) |
| Claude Code | max | max | 780–1,528 characters (941) |
| Oh My Pi | low | low | 201–344 tokens (272) |
| Oh My Pi | high | high | 402–846 tokens (654) |
| Oh My Pi | max | max | 486–1,061 tokens (635) |
| Hermes | low | low | 41–631 tokens (123) |
| Hermes | medium | medium | 366–2,223 tokens (538) |
| Hermes | high | high | 609–900 tokens (724) |
| Hermes | max | max | 426–803 tokens (596) |

Claude Code sent `thinking.type = "adaptive"` with `output_config.effort`
and no `budget_tokens`. One run using `CLAUDE_CODE_EFFORT_LEVEL=medium`
instead of the flag produced the same wire fields. Oh My Pi Flash sent
top-level `reasoning_effort` and omitted `thinking`. Spot checks of
`minimal` and `medium` both sent `low`, and `xhigh` sent `high`.
The relay observed reasoning in all these Flash Oh My Pi responses.
Hermes sent `thinking.type = "enabled"` and top-level `reasoning_effort`.
Spot checks of `minimal` and `xhigh` sent `low` and `max` respectively.

**Direct Messages budget probe.** With thinking enabled and no effort field,
Flash accepted every request at 1,024 and 8,192 budget tokens (five each)
and also accepted the single 256-token probe. The reasoning-text ranges for
1,024 and 8,192 overlapped (1,395–2,750 and 1,283–3,840 characters).
The responses did not expose a reasoning-token count or establish that Z.AI
enforced the supplied budget.

### Task quality check on Podman (2026-11-21)

`fr task check` (bead `fitting-room-2do`) runs Harbor's default rubric (11 criteria)
on the shared Podman base with Claude Code and GLM 5.3 Flash (`cc-glm53flash-high-authoring`).
The wrapper task is built by Harbor's own assembly code. It leaves out
`environment/repo/` and adds a note on the snapshot setup. The result is validated
with jq.

| Task | Time | Reward | Outcomes |
|---|---|---|---|
| `data-processing/label-busy-port` | 4 m 59 s | 1 | 11 pass |
| `sd-scripts/responsive-ctrl-c` | 4 m 12 s | 1 | 10 pass, 1 not applicable (`structured_data_schema`) |

The reviewers' explanations used the snapshot note correctly: no tests in the
image, the canonical `$VIRTUAL_ENV`, a single fresh commit. The first run surfaced a
report serialization bug. The trial itself was fine; the bug was fixed and covered by
a test. Results: `results/task-check/20261121-161220/` and `20261121-161803/`.
