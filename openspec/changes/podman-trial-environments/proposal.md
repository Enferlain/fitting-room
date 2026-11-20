# Proposal

## Why

The Docker setup from `benchmark-foundation` (design D8) treats every repo and every task as an image build. On 2026-11-19 that reached about 170 GB of images and build cache for five repos and two draft tasks:

- Each Python repo image carried the full uv cache as well as a venv copied out of it (sd-scripts: 29 GB).
- `COPY warm/` steps left whole repo trees in layers.
- Docker Desktop's containerd store keeps every layer twice, compressed and unpacked.
- Rebuilds re-download everything: Docker Desktop's BuildKit GC caps cache mounts at 2.7 GiB, so caches can't persist between builds.

Builds took hours whenever PyPI was slow, which it was that evening (about 60 KB/s). Docker Desktop's disk image also lives on C, and benchmarks must not run on C.

Very little actually differs between tasks: the repo state at one commit (MB), sometimes a few dependencies, and the harness under test. Everything heavy is per repo or per machine, and the host already has most of it:
- the repo environments;
- a 9.9 GB uv cache;
- the interpreters;
- the GPU driver.

## What Changes

- **Trials run under rootless Podman inside WSL** (NixOS distro at `D:\WSL\NixOS`), through Harbor's Podman environment with a thin fitting-room subclass. Docker Desktop is no longer used by fitting-room.
- **No per-task or per-repo image builds.** All trials start from one small base image. A task points at it with `[environment] docker_image`, so Harbor skips building.
- **Heavy state lives once in a store on the WSL disk** and is mounted read-only:
  - one canonical dependency environment per repo, made with uv hardlinks from the host cache;
  - interpreters;
  - harness installs, one per harness version;
  - toolkit binaries.
- **The task snapshot is a directory** prepared by `fr task materialize`, already re-initialised as one commit. It is mounted read-only and copied into the trial container, so agent writes vanish with the container.
- **GPU access binds `/dev/dxg` and `/usr/lib/wsl`.** The task GPU is pinned with `CUDA_VISIBLE_DEVICES=<uuid>`.
- **The existing Docker images and their recipes are retired:**
  - `images/repo-*` and `images/toolkits` go;
  - the task template `Dockerfile` goes;
  - `toolkit.toml`'s `dockerfile_append` is replaced by store mounts.

## Capabilities

### New Capabilities

- `trial-environments`: how a trial's filesystem, dependencies, harness, GPU and network are assembled. The rule: heavy state is stored once per repo or machine; a task adds only its snapshot; a trial leaves nothing behind except logs.

### Modified Capabilities

- `benchmark-foundation` design D2 (Docker backend) and D8 (per-repo base images) are superseded. D13's "install step run when the image is built" becomes "installed once into the store". The task-authoring requirements (no future history, verifier hidden, GPU tasks) are unchanged in substance. Only how they are met changes.

## Impact

- **New host tools:** podman and podman-compose (installed by the user: Nix profile or NixOS config).
- **User-level config** in `~/.config/containers/` (`policy.json`, `registries.conf`, `containers.conf`). These were created on 2026-11-19 for the spike.
- **Disk:**
  - Podman storage under `~/.local/share/containers/storage`, about 1–2 GB for the base and harness images;
  - the store, mostly hardlinks into `~/.cache/uv`.
  All of it is on D.
- **Code:**
  - new `src/fitting_room/environments/podman.py` and `src/fitting_room/store.py`;
  - changes to `tasks/materialize.py`, `runner.py` (environment type, overlays), `toolkits.py`, the adapters' `install()`, and the task template in the vendored skill.
- **Removed:**
  - every `fr-*` image in Docker Desktop;
  - `images/repo-python`, `repo-rust`, `repo-pytortch` and `toolkits/`;
  - `images/build.sh`. `images/base-cpu` stays as the base recipe, built with Podman.
- **Existing drafts:** the other session's two tasks (`label-busy-port`, `responsive-ctrl-c`) need their environment section rewritten.
