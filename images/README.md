# Images

Task images build in three layers:

1. `fr-base/cpu:1` (`images/base-cpu/`): Debian trixie, git, ripgrep, jq, build tools,
   uv 0.13.4, Node 24.21.0, openspec 1.15.0, bd 1.3.2 (release binary, checksum
   verified; metrics off), `DO_NOT_TRACK=1`, a sandbox git identity, and
   `fr-snapshot-init`.
2. `fr-repo/<repo>` (`images/build.sh <repo> [commit]`): the repo's toolchain, with
   dependency caches warmed from a recent commit. Settings per repo in
   `images/repos/<repo>.env` (`PYTHON`, `KIND`, optional `BASE`).
   - `repo-python`: `UV_PYTHON` pinned to the interpreter the repo's own venv uses; uv
     cache filled from `pyproject.toml` + `uv.lock`.
   - `repo-rust`: toolchain from `rust-toolchain.toml`; registry fetched and test
     binaries pre-built into `CARGO_TARGET_DIR=/opt/cargo-target`.
3. Task image (`tasks/<repo>/<slug>/environment/Dockerfile`):

   ```dockerfile
   FROM fr-repo/<repo>:latest
   WORKDIR /app
   COPY repo/ /app/
   RUN fr-snapshot-init && <install step: uv sync --frozen ... | cargo test --no-run ...>
   ```

`fr-snapshot-init` drops beads sync remotes (either YAML spelling), makes one `init`
commit, initialises bd from the snapshot's `.beads/issues.jsonl` (no hooks, no agent
files), folds bd's ignore-file edits into that commit, and clears the reflog. Result:
one commit, one ref, no reflog, no remotes, a clean tree, and `bd list` showing the
issues as they were at the snapshot.

## Verified (2026-11-19, tests run with `--network none`)

| Repo | Commit | Result |
|---|---|---|
| data-processing | `f7585cbc24` | full pytest suite passes |
| hermes-agora | `b140aefb03` | full pytest suite passes |
| hcom | `e215adc1c0` | `cargo test --workspace`: all pass except `db::tests::test_open_raw_rejects_temp_symlink_to_non_temp_path` (passes on the host; depends on the host's temp-dir layout). Exclude it in verifiers. |
| sd-scripts | | CUDA image, not built yet |
| pytortch-backend-experiments | | CUDA image, not built yet |
