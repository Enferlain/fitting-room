# Images

Task images build in three layers:

1. `fr-base/cpu:1` (`images/base-cpu/`): Debian trixie, git, ripgrep, jq, build tools,
   uv 0.13.4, Node 24.21.0, `DO_NOT_TRACK=1`, build parallelism capped at 8 jobs, a
   sandbox git identity, and `fr-snapshot-init`. No bd, openspec or codebase-memory:
   nothing is enabled by default.
2. `fr-repo/<repo>` (`images/build.sh <repo> [commit]`): the repo's toolchain, with
   dependency caches warmed from a recent commit. Settings per repo in
   `images/repos/<repo>.env` (`PYTHON`, `KIND`, optional `BASE`).
   - `repo-python`: `UV_PYTHON` pinned to the interpreter the repo's own venv uses; uv
     cache filled from `pyproject.toml` + `uv.lock`.
   - `repo-rust`: toolchain from `rust-toolchain.toml`; registry fetched and test
     binaries pre-built into `CARGO_TARGET_DIR=/opt/cargo-target`.
3. Task image (`tasks/<repo>/<slug>/environment/Dockerfile`), repo at `/work/<repo>`
   (codebase-memory refuses top-level roots such as `/app`):

   ```dockerfile
   FROM fr-repo/<repo>:latest
   WORKDIR /work/<repo>
   COPY repo/ /work/<repo>/
   RUN fr-snapshot-init && <install step: uv sync --frozen ... | cargo test --no-run ...>
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

After large builds run `images/compact-memory.sh`: it drops the VM page cache and
compacts memory so WSL can return it to Windows (`autoMemoryReclaim=gradual` only
returns whole 2 MB blocks).

## Verified (2026-11-19, tests run with `--network none`)

| Repo | Commit | Result |
|---|---|---|
| data-processing | `f7585cbc24` | full pytest suite passes |
| hermes-agora | `b140aefb03` | full pytest suite passes |
| hcom | `e215adc1c0` | `cargo test --workspace`: all pass except `db::tests::test_open_raw_rejects_temp_symlink_to_non_temp_path` (passes on the host; depends on the host's temp-dir layout). Exclude it in verifiers. |
| data-processing + dev-stack | `f7585cbc24` | one clean commit; bd lists the snapshot's issues; openspec runs; codebase-memory index ready (12,610 nodes) |
| sd-scripts | | not built yet (opencv-python has no 3.14t wheel; compiles from source) |
| pytortch-backend-experiments | | CUDA image, not built yet |
