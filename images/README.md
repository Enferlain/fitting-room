# Images

Task images build in three layers:

1. `fr-base/cpu:1` (`images/base-cpu/`): Debian trixie, git, ripgrep, jq, build tools,
   uv 0.13.4, Node 24.21.0, `DO_NOT_TRACK=1`, build parallelism capped at 8 jobs, a
   sandbox git identity, and `fr-snapshot-init`. No bd, openspec or codebase-memory:
   nothing is enabled by default.
2. `fr-repo/<repo>` (`images/build.sh <repo> [commit]`): the repo's toolchain, with
   dependency caches warmed from a recent commit. Settings per repo in
   `images/repos/<repo>.env` (`PYTHON`, `KIND`, optional `BASE`).
   - `repo-python`: `UV_PYTHON` pinned to the interpreter the repo's own venv uses and
     one shared venv at `/opt/venv` (`UV_PROJECT_ENVIRONMENT`) synced from
     `pyproject.toml` + `uv.lock`. The image holds the interpreter and that venv only.
     The uv cache is **not** in any image (it was 11 GB of the old 29 GB sd-scripts
     image): builds use a BuildKit cache mount (`id=fr-uv-cache`, target
     `/opt/uv-cache`) so it never lands in a layer. Docker Desktop's BuildKit GC caps
     cache mounts at 2.7 GiB, so it does not persist: rebuilding a repo image
     re-downloads its wheels (sd-scripts also recompiles free-threaded opencv). A task
     image that needs its commit's own dependencies (or the project installed) adds
     only what differs:

     ```dockerfile
     RUN --mount=type=cache,id=fr-uv-cache,target=/opt/uv-cache,sharing=locked \
         uv sync --frozen $FR_SYNC_ARGS && fr-snapshot-init
     ```

     Verifiers call `/opt/venv/bin/python` directly and work offline either way.
     `SYNC_ARGS` per repo (sd-scripts: `--extra onnx-gpu --all-groups`, its onnx extras
     conflict).
   - `repo-pytortch`: FROM the sd-scripts image; see the table below. Task images run
     `fr-snapshot-init && fr-pytortch-setup`.
   - `repo-rust`: toolchain from `rust-toolchain.toml`; registry fetched and test
     binaries pre-built into `CARGO_TARGET_DIR=/opt/cargo-target`.
3. Task image (`tasks/<repo>/<slug>/environment/Dockerfile`), repo at `/work/<repo>`
   (codebase-memory refuses top-level roots such as `/app`):

   ```dockerfile
   FROM fr-repo/<repo>:latest
   WORKDIR /work/<repo>
   COPY repo/ /work/<repo>/
   RUN fr-snapshot-init   # plus the repo's install step, see above
   ```

`fr-snapshot-init` drops beads sync remotes (either YAML spelling), makes one `init`
commit and clears the reflog: one commit, one ref, no reflog, no remotes, a clean tree.

4. Toolkit layer, only when a run enables `dev-stack` (`images/toolkits/dev-stack/`,
   image `fr-toolkit/dev-stack:1`):

   ```dockerfile
   COPY --from=fr-toolkit/dev-stack:1 /opt/fr-toolkit /opt/fr-toolkit
   RUN /opt/fr-toolkit/setup.sh
   ```

   It carries bd 1.3.2 (release binary, checksum verified, metrics off), openspec
   1.15.0 and codebase-memory-mcp `0.12.1-fork.1` (the user's fork, built static by
   `images/cbm/build.sh` into `fr-tool/cbm`). `setup.sh` puts them on PATH, initialises
   bd from the snapshot's `.beads/issues.jsonl` (no hooks, no agent files), indexes the
   repo for codebase-memory, and folds bd's ignore-file edits back into the single
   commit. Harness wiring (MCP registration, hooks, skills) is task 4.6.

## Disk use

Per-image cost (2026-11-19, `docker system df -v`, size not shared with other images):
sd-scripts 12.3 GB (includes the 1 GB base), its 3.13 variant 9.8 GB, pytortch 6.7 GB on
top of sd-scripts, hcom 4.4 GB, data-processing 0.7 GB, hermes-agora 0.2 GB: 35 GB for
all six, down from about 170 GB of images plus build cache. Docker Desktop's containerd
image store keeps each layer compressed as well as unpacked, so sizes run above `du`. Task images are thin layers on their repo
image (the snapshot plus one commit, tens of MB), so a new task does not add a venv or a
toolchain. A new repo image is only needed for a different interpreter (e.g. the 3.13
sd-scripts image) or a different toolchain. Clean up with:

```sh
docker image prune                             # dangling layers from rebuilds
docker builder prune                           # build cache (layers from earlier builds)
```

After large builds run `images/compact-memory.sh`: it drops the VM page cache and
compacts memory so WSL can return it to Windows (`autoMemoryReclaim=gradual` only
returns whole 2 MB blocks).

## Historical Python snapshots

Use the task's `[metadata] start_commit` and check that revision's
`requires-python` before picking an interpreter. For example:

```sh
FR_IMAGE_PYTHON=3.13 images/build.sh sd-scripts 51ead689c647d
```

The override warms the lockfile at that commit with Python 3.13 and tags
the image as `fr-repo/sd-scripts:51ead689c6-py3.13`. The repo's normal
commit tag and `:latest` tag stay available for the default build.
Pin the interpreter-specific tag in a new task
image, and run its focused `uv run pytest` command with Docker networking
disabled before the first smoke run.

## Verified (2026-11-19, tests run with `--network none`)

| Repo | Commit | Result |
|---|---|---|
| data-processing | `f7585cbc24` | full pytest suite passes |
| hermes-agora | `b140aefb03` | full pytest suite passes |
| hcom | `e215adc1c0` | `cargo test --workspace`: all pass except `db::tests::test_open_raw_rejects_temp_symlink_to_non_temp_path` (passes on the host; depends on the host's temp-dir layout). Exclude it in verifiers. |
| data-processing + dev-stack | `f7585cbc24` | one clean commit; bd lists the snapshot's issues; openspec runs; codebase-memory index ready (12,610 nodes) |
| sd-scripts | `38cdc295ee` | free-threaded 3.14t; image 12.3 GB (interpreter + shared venv; was 29 GB with the uv cache in the image; opencv-python compiled once, as on the host). Unit suite with the 3080 pinned (`--gpus all -e CUDA_VISIBLE_DEVICES=<3080 UUID>`): 2,577 passed vs 2,569 on the host checkout; the failures are the host's own (stale tests mid-rework, e.g. `library.vendor.lycoris` imports) except `test_bookkeeping_and_peak_memory_stay_flat_as_a_run_grows_tenfold` (memory-growth check, sensitive to `-n 8`). Without a GPU, strategy tests error with "Found no NVIDIA driver". |
| sd-scripts | `51ead689c6` | Python 3.13.16 in `:51ead689c6-py3.13`. The focused interrupt tests passed with ordinary `uv run pytest` on both the starter and reference, four tests each. |
| pytortch-backend-experiments | `0ad1b25474` | Built FROM the sd-scripts image: `stage0/.venv` links `/opt/venv` without Triton via the repo's `isolate_python.py` (as on the host); NVRTC and CUDA headers from torch's nvidia packages; Rust 1.99.1 and a pre-built native target (symlinked; task layer 515 MB). Snapshot excludes `stage5/artifacts/*/**` (16,291 generated files). `cubecl_torch/testing` on the 3080: 626 passed, 9 skipped, 7 failed: all `test_binding_equals_stage5`, which needs `stage0/target/release/cubecl-stage0`, built from the gitignored `.stage0-sources/cubecl` (CubeCL 6bba5fdf) and present only on the host. Stage 5 equivalence is retired (AGENTS.md); exclude these in verifiers. |
