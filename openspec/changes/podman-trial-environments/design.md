# Design

## Context

`benchmark-foundation` built one Docker image per repo (toolchain plus a venv warmed from a recent commit), and one more per task (`FROM` the repo image, `COPY` the snapshot, `RUN fr-snapshot-init`). It works, but cost and time grow with every repo, interpreter and rebuild, and Docker Desktop's disk is on C (see proposal). This change keeps Harbor (D1) and everything above the environment layer:
- run configs and campaigns;
- adapters;
- ATIF trajectories;
- verifiers and scoring.

It replaces how a trial's environment is assembled.

**Principle:** anything heavy exists once per machine or per repo and is mounted read-only. A task contributes only its snapshot. A trial contributes only its writes, which are discarded, plus its logs. Running N tasks in sequence costs the disk of one.

## Verified on this host (2026-11-19, Podman 5.x from `nix shell nixpkgs#podman`)

| Check | Result | How |
|---|---|---|
| Rootless Podman | works (`rootless=true`, netavark + pasta) | `podman run --rm alpine id` |
| Storage location | `~/.local/share/containers/storage`, overlay driver, on the NixOS disk at `D:\WSL\NixOS` | `podman info`; `HKCU\...\Lxss` BasePath |
| GPU | 3080 and 3090 visible. With `CUDA_VISIBLE_DEVICES=GPU-510ddc27-…`, torch sees 1 device (the 3080) and ran a 4096² matmul in 3.8 s including startup | `--device /dev/dxg -v /usr/lib/wsl:/usr/lib/wsl:ro -e LD_LIBRARY_PATH=/usr/lib/wsl/lib` |
| CDI | **does not work as generated**: `nvidia-ctk cdi generate --mode=wsl` writes `/usr/bin/nvidia-cdi-hook`, which doesn't exist on NixOS. Use the plain bind above instead (or regenerate with `--nvidia-cdi-hook-path`). | |
| Host env mounted read-only into a stock image | the host's `sd-scripts/.venv-wsl` plus `~/.local/share/uv/python`, bound at the **same paths** into `debian:trixie-slim`, imported torch and ran CUDA | `-v $P:$P:ro -v $V:$V:ro` |
| Copy-on-write mount `:O` | works with `podman run` (the host directory was unchanged), but **not through compose**: via docker-compose and the Podman API it became a plain read-write bind (2026-11-20). See P3. | `-v src:/work/repo:O` |
| Agent Vault | `api.z.ai` resolves to the FakeIP (198.18.0.4) inside containers. `GET /api/coding/paas/v4/models` with the placeholder key returned 200, TLS verified against `work/certs/ca-bundle.crt` | curl image |
| Host services (llama-swap on 127.0.0.1) | **not** reachable through `host.containers.internal` by default. Reachable with `--network pasta:--map-host-loopback=169.254.1.2` (`host.containers.internal` resolves to 169.254.1.2). WSL is in mirrored networking mode, so Windows' 127.0.0.1 is WSL's. | python http.server on 127.0.0.1:18099 |

**Not yet verified, so the spike (tasks 2.x) checks these:**
- `:O` and the extra mounts through Harbor's compose path (podman-compose versus `podman compose` → docker-compose over the Podman socket);
- Harbor's egress-control sidecar under Podman (Harbor ships Podman support for it);
- `uv run` against a read-only env;
- harness installs from a mounted store.

## Decisions

### P1. Rootless Podman in WSL, through a Harbor environment subclass
`src/fitting_room/environments/podman.py`: `FrPodmanEnvironment(PodmanEnvironment)`, loaded with the job config's `environment.import_path`. Harbor's Podman environment is its Docker environment with another CLI. The subclass:
- declares `gpus=True` in `capabilities` and, for a GPU task, adds the `/dev/dxg` device, the read-only `/usr/lib/wsl` bind, `LD_LIBRARY_PATH` and `CUDA_VISIBLE_DEVICES` (Harbor only wires GPUs for Docker);
- computes the per-task mounts (P3–P6) from the task's `task.toml` `[metadata]` and the run's toolkit. A job covers many tasks, so mounts cannot be job-level;
- sets pasta's `--map-host-loopback` (per container, or once in `containers.conf` `[network] pasta_options`) so `host.containers.internal:18080` reaches llama-swap;
- keeps the run-level Agent Vault CA overlay unchanged (`work/overlays/agent-vault-ca.compose.yaml`);
- sets `init: true` on the main service, so `down` doesn't wait 10 s on `sleep infinity`.

The runner (spike findings, 2026-11-20) calls Harbor with:
- `PATH` without `/mnt/*` entries: about 1 s saved per Podman call;
- `PODMAN_COMPOSE_PROVIDER` set to nixpkgs' docker-compose, a Compose V2 dialect for `cp` and `exec --no-TTY`. The user's global setting stays podman-compose;
- `environment.delete = false`. With delete on, Harbor's `down --rmi local` removed the shared base image.

*Alternative considered:* a bubblewrap environment written from scratch (no images at all). Rejected for now. It works on this host (bwrap and unprivileged overlayfs are available), but it means rewriting what Harbor's Docker/Podman environment already does (exec, upload/download, egress sidecar, compose overlays). Podman gives the same economics with far less new code.

### P2. One base image, no per-task builds
- **The base** is `fr-base/cpu:1` (`images/base-cpu/Dockerfile`, unchanged: Debian trixie, git, rg, jq, build tools, uv, Node), built once with `podman build`. About 1 GB, shared by every trial.
- **Rust** (hcom, pytortch's native crates) gets one extra image, `fr-base/rust:<toolchain>`, if the toolchain can't be mounted. NixOS-built rustup toolchains don't run on Debian, so the toolchain lives in that image or in the store, installed from inside a container.
- **Tasks** set `[environment] docker_image = "fr-base/cpu:1"`, and Harbor uses `docker-compose-prebuilt.yaml` with no build. `environment/Dockerfile` is dropped from the task template.

### P3. Snapshot prepared on the host, copied into the container at start
`fr task materialize` already writes `environment/repo/` (`git archive`, excludes, stripping). It additionally runs the `fr-snapshot-init` steps on the host:
1. drop beads sync remotes;
2. `git init`, `gc.auto 0`;
3. one `init` commit;
4. expire the reflog, `gc`.

The snapshot then holds one commit, no remotes, no hooks and no reflog. The leak probe runs against the directory. Its check for `environment/Dockerfile` goes away.

**Decided by the spike (2026-11-20):** the trial mounts the snapshot **read-only** at `/opt/fr-snapshot`, and the container copies it to `/work/<repo>` at start: `cp -a` in the main service's command, or an exec in the subclass's `start()` with a ready marker. The copy lives in the container's writable layer: visible to the verifier, gone with the container. `:O` copy-on-write mounts were the first idea, but through compose and the Podman API they silently become read-write binds (`docs/spikes.md`, Podman section).

### P4. One canonical benchmark environment per repo

Repo configuration pins the source commit, interpreter and sync arguments for the canonical benchmark environment. `fr env ensure <repo>` creates that environment on demand. Change those inputs explicitly at the repo benchmark level and revalidate the affected tasks. Task snapshots, historical lockfiles and interpreter declarations never select or create a different environment.

A repo may be a composite: `kind = "python+rust"` adds a pinned Rust toolchain and the crates of the listed `rust_manifests` to the Python environment, warmed at the canonical commit into a shared target cache (`CARGO_TARGET_DIR`), and offline in trials. sd-scripts is one (2026-11-20, user): its Pliron candidate crate is needed by N7. Warmed targets keep dependencies only: each workspace member's own artifacts are removed after warming (they were built from the canonical commit, newer than most snapshots), so trials compile the repo's own crates from their snapshot. Every task of a composite repo gets the whole composite; there are no task-specific Rust environments. The store GC keeps both halves.

`fr env check <task>` reports the task snapshot's lock differences for diagnosis. Validate each task on the canonical environment. A historical task that fails for dependency or interpreter reasons must be adapted without changing its substance, or excluded.

Extract the pinned `pyproject.toml` and `uv.lock` into a temporary project and sync with `UV_LINK_MODE=hardlink uv sync --frozen --no-install-project`. The existing uv cache and store must share a filesystem. Use a managed interpreter under `$FR_STORE/python/`. Record the input digest and actual interpreter in the run provenance.

Mount the environment and its interpreter read-only at their original absolute paths. Set `VIRTUAL_ENV`, `UV_PROJECT_ENVIRONMENT`, `PATH` and `UV_NO_SYNC=1`. Expose the trial source tree through a generated `.pth` and console scripts based on the canonical project metadata.

For Rust, mount the warmed Cargo home, toolchain and target cache read-only. Copy Cargo home and the target cache into trial-local storage so Cargo can take locks and write build outputs. Use reflinks where supported. For pytortch, the Tracel LLVM SDK is part of the read-only seed, mounted at the same XDG data path used during warming. The compose path does not preserve `:O` (P3).

The store defaults to `~/.local/share/fitting-room/store`. Set `FR_STORE=/opt/fr-store` to use a neutral mount path. `fr doctor` checks rootless Podman and the storage paths, including the filesystem shared with the uv cache. `fr store gc` previews stale keys and unused harness versions. `--apply` waits for active campaigns to release their store locks before removing entries.

### P5. Harness installs: once per harness version, mounted
Harbor reinstalls the harness in every trial (no install cache). Hermes takes about 6 minutes, and npm and PyPI downloads every time. Instead:
- **Installed once:** `fr harness ensure <name> <version>` installs into `$FR_STORE/harness/<name>/<version>/`, run in a throwaway container from the base image so binaries match Debian:
  - npm prefix for codex, claude-code and opencode;
  - omp release binary;
  - the Hermes venv at its pinned commit.
- **Mounted:** read-only. The adapters' `install()` becomes "verify the mounted install and put it on PATH". The fitting-room subclasses own this, extending the existing thin subclasses (`adapters/hermes.py`, `adapters/omp.py`) and adding them for codex, claude-code and opencode (overlaps foundation task 4.2).
- **Version check:** each harness's `--version` output is checked against the pin at trial start, as now.

### P6. Toolkits become store mounts
`dev-stack` is bd and openspec. codebase-memory was removed on 2026-11-20 (user): its index writes far too much for what the benchmark needs. The two binaries come from `fr-toolkit/dev-stack:1` through `dockerfile_append` today. They move to `$FR_STORE/toolkits/dev-stack/<digest>/`, mounted read-only on PATH.

`bd init --from-jsonl --non-interactive --skip-hooks --skip-agents` stays a per-trial setup step. It's small and fast, and it writes into the trial's writable layer, so it vanishes with the trial. MCP and skill items stay supported for future toolkits.

`toolkit.toml` replaces `dockerfile_append` with a `store` section; the schema change is in task 5.x.

### P7. Network
Standalone web research uses public egress. Public-upstream coding tasks use Harbor's agent-phase allowlist. Model endpoints go through Agent Vault (GLM) or llama-swap (local).
- Agent Vault works as-is (verified).
- llama-swap needs `--map-host-loopback` (P1).
- Harbor's Podman egress sidecar enforces the allowed hosts during the agent phase. For public-upstream coding tasks, omit the upstream host from the allowlist. The `netallow` spike verifies that GitHub is blocked even when PyPI is allowed. The separate `web-research` spike exercises public HTTPS as part of the requested work.

### P8. Retiring the Docker artifacts
After the pilot task passes under Podman:
- **Images:** delete every `fr-*` image from Docker Desktop.
- **Recipes:** remove `images/repo-python`, `images/repo-rust`, `images/repo-pytortch`, `images/toolkits` and `images/build.sh`. Keep `images/base-cpu`. The host materializer implements the former `images/common/fr-snapshot-init` steps.
- **Code and docs:**
  - update the vendored skill's task template and `UPSTREAM.md`;
  - update `docs/running.md`, `docs/harnesses.md` and `images/README.md`;
  - mark `benchmark-foundation` D2 and D8 as superseded by this change.

## Cost model (target)

| Item | Disk | Time |
|---|---|---|
| Base image | about 1 GB once | built once |
| Harness install | about 0.1–1 GB per harness version, once | once |
| Canonical env per repo | about 0 (hardlinks), plus wheels missing from the cache | seconds |
| Task | snapshot MBs (pytortch about 110 MB) | `fr task materialize`: seconds |
| Trial | overlay upper (agent's writes) until the container is removed; logs kept | container start in seconds; no build, no install |

Acceptance: a 10-task sequential campaign adds no image layers. Its disk after cleanup is snapshots plus logs.

## Risks / Trade-offs

- **The `:O` option or extra mounts don't pass through Harbor's compose.** Fallback: upload the snapshot (P3), and give a subclass mounts through `extra_docker_compose` generated per trial. The spike's first check.
- **Host-path mirroring shows the username in sandboxes.** Accepted, or avoided with `/opt/fr-store`.
- **Reproducibility.** The canonical inputs and actual interpreter version are recorded. The store is separate from the user's working venvs, so editing those doesn't change results. Wheels come from the user's uv cache, so pruning that cache only costs re-downloads.
- **Rootless Podman and the GPU pin.** `CUDA_VISIBLE_DEVICES` stays a soft pin (same as under Docker Desktop). An agent could unset it. Recorded as a known limitation, as before.
- **Podman and Docker Desktop together.** They're independent. Docker Desktop's WSL integration doesn't touch Podman's socket or storage. Don't set `DOCKER_HOST` globally.
- **Network speed.** PyPI and crates.io were very slow on 2026-11-19. With envs hardlinked from the existing cache, most environments need no downloads at all.

## Decided (formerly open questions)

- **Podman install:** NixOS module (`virtualisation.podman.enable = true`, `dockerCompat = false`), done by the user on 2026-11-20. `/opt/fr-store` (tmpfiles) is not set up, so `$FR_STORE` defaults to `~/.local/share/fitting-room/store`.
- **Compose frontend:** `podman compose` with a fitting-room-local provider, nixpkgs' docker-compose over the Podman socket, pinned as a Nix GC root at `$FR_STORE/tools/docker-compose` (`nix build nixpkgs#docker-compose -o "$FR_STORE/tools/docker-compose"`; `FR_PODMAN_COMPOSE_PROVIDER` overrides), set by the runner only for its Harbor calls. The user's global `PODMAN_COMPOSE_PROVIDER` (podman-compose) stays. podman-compose 1.5 lacks `cp` and `exec --no-TTY`.
- **Project install (P4):** `UV_NO_SYNC=1` plus a generated `.pth` and console scripts for the project source (spike 2.4: `uv run` tried to build the project from PyPI and failed under the allowlist).
- **`environment.delete = false`:** checked in Harbor 0.26's `DockerEnvironment.stop()`. It still runs `compose down` (containers and networks removed) and only omits `--rmi local --volumes --remove-orphans`. No named volumes are used, so nothing piles up. Verified: 0 containers, networks or volumes after trials.
