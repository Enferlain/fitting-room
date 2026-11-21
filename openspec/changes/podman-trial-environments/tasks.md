# Tasks

Read `design.md` first: its "Verified on this host" table records what is already proven and the exact commands used. Spike results go into `docs/spikes.md` under a new "Podman" section.

## 1. Host setup (user decision first)

- [x] 1.1 Podman and a compose frontend installed permanently (user's choice: `nix profile install nixpkgs#podman nixpkgs#podman-compose`, or NixOS `virtualisation.podman.enable = true`, plus `/opt/fr-store` via tmpfiles if wanted). Verify `podman info` reports `rootless=true` and a graph root under `/home`, and that `podman compose version` (or `podman-compose version`) runs
- [x] 1.2 User config in `~/.config/containers/`: keep `policy.json`, `registries.conf` and `containers.conf` from the spike, and add `[network] pasta_options = ["--map-host-loopback", "169.254.1.2"]`. Drop the unused CDI spec in `~/.config/cdi/` (it points at a missing `/usr/bin/nvidia-cdi-hook`). Verify a container reaches a host test server on 127.0.0.1 through `host.containers.internal`
- [x] 1.3 Build `fr-base/cpu:1` with `podman build images/base-cpu`, and verify its size is about 1 GB and the build pulls only Debian, uv and Node

## 2. Spike: one existing task end to end under Podman (decides the open questions)

- [x] 2.1 Harbor's Podman environment runs the hello-world task with oracle and nop (rewards 1 and 0), with the compose frontend from 1.1. Record which frontend Harbor resolved
- [x] 2.2 (Result: `:O` does not pass through compose and the Podman API; it became read-write. Read-only binds work. Snapshot is copied in at start; see design P3.) A `:O` bind mount and a read-only bind mount pass through Harbor (job `environment.mounts` or a compose overlay). Verify the container sees both, and that a write under the `:O` mount doesn't reach the host. If not, switch to the upload fallback (design P3) and record why
- [x] 2.3 `tasks/data-processing/label-busy-port` with `docker_image = "fr-base/cpu:1"` (no Dockerfile build), the snapshot mounted read-only and copied in at start (design P3; `:O` was dropped, see 2.2) and the data-processing env from the store mounted read-only: oracle passes, nop fails. Record startup time and the disk delta after the trial
- [x] 2.4 (Result: reward 1, no infra error. `uv run` failed building the project offline, so P4 option (b) chosen; see docs/spikes.md.) The same task with one real harness (Claude Code + GLM 5.3 through Agent Vault) passes or fails on merit, with no infrastructure error. Check what `uv run` does against the read-only env, and pick design P4 option (a), (b) or (c)
- [x] 2.5 Egress allowlist under Podman: `spikes/netallow` (foundation spike 2.3) blocks `github.com` and allows the model endpoint
- [x] 2.6 GPU: `tasks/sd-scripts/responsive-ctrl-c` (or a minimal torch task) under Podman with the 3080 pinned: torch sees exactly the 3080. Record results 2.1–2.6 in `docs/spikes.md`, then user checkpoint: go or no-go on the rest

## 3. Store and environments

- [x] 3.1 `src/fitting_room/store.py`: `$FR_STORE` resolution (default `~/.local/share/fitting-room/store`, or `/opt/fr-store`), a same-filesystem check against `~/.cache/uv`, and a refusal for paths under `/mnt/`. Unit tests
- [x] 3.2 Canonical env per repo (design P4): `fr env ensure <repo>` with `UV_LINK_MODE=hardlink`, interpreter in `$FR_STORE/python`, lock and interpreter version written to `env.json`. Verify the sd-scripts env is mostly hardlinks into `~/.cache/uv` and can be recreated offline once the cache is populated
- [x] 3.2b `fr env check <task>` (P4): report lock differences against the canonical env without changing it. Verify that historical differences cannot create an environment
- [x] 3.3 Rust: registry and per-repo target cache in the store (P4). Toolchain in an `fr-base/rust` image or in the store, installed from a container. Verify hcom's `cargo test --workspace --no-run` runs offline in a trial and a second trial reuses the target cache
- [x] 3.4 pytortch: `stage0/.venv` linking the sd-scripts env without Triton (`isolate_python.py`), plus the native build into the target cache (replaces `images/repo-pytortch/fr-pytortch-setup`). Verify the `cubecl_torch/testing` subset from `images/README.md` passes on the 3080 (626 passed, 9 skipped, 7 retired Stage 5 equivalence cases deselected)
- [x] 3.5 `fr store gc`: list and remove envs and harness installs no task or run config references. Verify on a fixture store

## 4. Fitting-room Podman environment

- [x] 4.1 `src/fitting_room/environments/podman.py`, `FrPodmanEnvironment(PodmanEnvironment)`: per-task mounts from `task.toml` `[metadata]` (read-only snapshot copied into trial storage, env and interpreter read-only at identical paths, toolkit and harness mounts), the env variables (`VIRTUAL_ENV`, `UV_PROJECT_ENVIRONMENT`, `PATH`, `UV_NO_SYNC` per P4), `gpus` capability and WSL GPU wiring with `CUDA_VISIBLE_DEVICES`. Unit tests on the generated compose and mounts
- [x] 4.2 `runner.py`: `environment.import_path` set to the subclass. The Agent Vault CA overlay is kept. `fitting_room.json` records the env key, interpreter, harness store path and toolkit digest. `fr run` ensures the repo environment before Harbor. Update `tests/test_runner.py`
- [x] 4.3 Storage check (spec "Benchmark storage is off C"): `fr doctor` or a pre-run check. Verify it fails when `FR_STORE` points under `/mnt/c`

## 5. Harness and toolkit stores

- [x] 5.1 `fr harness ensure <name> <version>` installs into `$FR_STORE/harness/<name>/<version>/` from a throwaway base container (npm prefix for codex, claude-code and opencode; omp binary; Hermes at the pinned SHA, without browser extras). Write `harness.json` with `harness` and `version` for store GC. Have `fr run` provision the pinned harness before Harbor
- [x] 5.2 Adapters' `install()` uses the mounted install (verify `--version` against the pin), for all five harnesses. Overlaps foundation 4.2: do the thin pinned subclasses for codex, claude-code and opencode here. Verify each harness's smoke task starts in under 30 s with no network install
- [x] 5.3 Toolkits: `toolkit.toml` loses `dockerfile_append` and gains a store install. `dev-stack` binaries in `$FR_STORE/toolkits/dev-stack/<digest>/`. `bd init` stays per trial (into the repo overlay). Rework `spikes/toolkit-check` to bd and openspec only, and re-run it with Claude Code, omp and Hermes

## 6. Tasks, template, docs, cleanup

- [x] 6.1 `fr task materialize` runs the snapshot-init steps on the host (one commit, no remotes or hooks or reflog, beads sync remotes stripped). The leak probe runs on the directory. Update `tests/test_materialize.py`
- [x] 6.2 Task template in the vendored skill: no `environment/Dockerfile`; `[environment] docker_image = "fr-base/cpu:1"` (or the rust base). Update `UPSTREAM.md`. Migrate compatible drafts, adapting them to the canonical environment where needed, and verify they validate (oracle 5/5, nop 0) under Podman
- [x] 6.3 Docs: `docs/running.md` (Podman setup, store, `fr env` and `fr harness`), `docs/harnesses.md` (installs from the store), `images/README.md` (only base images remain), `docs/spikes.md`. Mark `benchmark-foundation` design D2 and D8 superseded, with a pointer here
- [x] 6.4 Retire Docker: remove `images/repo-*`, `images/toolkits`, `images/build.sh` and the Docker-specific runner code; delete the `fr-*` images from Docker Desktop. Verify `uv run pytest` and ruff pass, and that `docker images | grep fr-` is empty
- [x] 6.5 Acceptance: a campaign of the available tasks run in sequence with oracle (3 repeats) builds no images. Record the disk delta (store and Podman graph root before and after) in `CHANGELOG.md`
