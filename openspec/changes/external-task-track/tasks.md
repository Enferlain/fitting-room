# Tasks

## 1. Secure the incoming material

- [x] 1.1 Copy the `docs/domain-tasks/` zips and the research doc into `work/domain-tasks/archive/` and extract them into `work/domain-tasks/private/{audit,author,trials,runtime}/`. Verify `git status --ignored` shows them only as ignored, and that the zips' SHA-256 matches the originals.
- [x] 1.2 Put the answer-free material in `docs/external-tasks/` (`README.md` with the private-material rule and backup note, `task-coverage.md`, `candidates.toml` with answer-hinting notes scrubbed, `grid.py`, `index.md`, `scores.md`, `runtime/`), then delete `docs/domain-tasks/`. Verify that no file under `docs/` mentions an oracle value or an expected answer (spot-check by grepping for the C48 and C13 claim keys).

## 2. Coverage tags and grid

- [ ] 2.1 Implement `src/fitting_room/tasks/coverage.py` (loader, vocabularies, grid, gaps, marginals, fill-rule marking) as a port of `grid.py`, reading `tasks/**/task.toml` `[metadata.coverage]` plus `docs/external-tasks/candidates.toml`. Verify with unit tests on fixture trees: a missing field, an unknown domain, dropped and lead excluded, an authored candidate counted once, and a source-evidence filler marked below the rule.
- [ ] 2.2 Add `fr tasks grid [--min N]` and verify that on the current `candidates.toml` alone its output matches `python docs/external-tasks/grid.py docs/external-tasks/candidates.toml`, apart from the new fill-rule markers.
- [ ] 2.3 Tag `tasks/data-processing/label-busy-port` and `tasks/sd-scripts/responsive-ctrl-c` with `[metadata.coverage]`, and verify `fr tasks grid` reports 2 internal tasks with no warnings.

## 3. Upstream materialize and hydrate

- [ ] 3.1 Add the upstream source mode to `fr task materialize` (design D2): clone into `$FR_REPOS_DIR/external/<repo>`, `git archive <commit> -- <manifest>`, overlay `visible/`, single fresh commit, digest check against the task's expected digests. Verify with tests that two runs give byte-identical snapshots, that a missing commit fails naming repo and commit, that a tampered overlay file fails naming the file, and that the snapshot has no `.git` history beyond one commit.
- [ ] 3.2 Add `fr task hydrate <task>`, which copies `tests/` and `solution/` from `work/domain-tasks/private/<id>/`, and add `.gitignore` entries for `tasks/external/*/{tests,solution,environment}/`. Verify that after hydrating, `git ls-files tasks/external` lists only `task.toml`, `instruction.md`, `manifest.txt`, `provenance.md` and `visible/`.
- [ ] 3.3 Extend the leak probe for external tasks so it also searches the trial for strings that occur only in the expected answer, oracle or near-miss. Verify that it flags a deliberately planted `expected.json` and passes on a clean C45 snapshot.

## 4. Environments and store components

- [ ] 4.1 Support `kind = "external"` repo configs (`upstream`, `python`, hash-pinned `requirements`) in `fr env ensure`, with the code under test reachable only from `/work/<repo>`. Verify with a test that `import <pkg>` resolves inside the trial working copy and that the store environment has no copy of the package under test.
- [ ] 4.2 Add repo configs and pinned requirements for `langgraph`, `openai-agents`, `tinygrad`, `pytorch-custom-op` (C35, PyTorch 2.15.0+cpu), `meson`, `tokenizers` and `pybind11`, generated from `requirements-*.txt` and `environment.lock`. Verify that `fr env ensure` builds each one and that the dist-info versions match `environment.lock`.
- [ ] 4.3 Add store components for CPython 3.14.10 and 3.14.10t, CMake 4.4.5 + Ninja 1.13.2, and Rust 1.100.0 with the C04 vendored crates. Verify that `fr env check` reports each one, and that an offline `cargo build --offline` of C04's bindings succeeds against the read-only vendor mount.

## 5. Verifier and validation controls

- [ ] 5.1 Implement the claim-ledger verifier contract (design D4: `claims.json`, `claim_threshold`, malformed-answer handling) and C13's `scores.json` with behavior and review sub-scores. Verify with unit tests: full, partial (42/49 → reward 0), missing answer and malformed answer.
- [ ] 5.2 Add solution variants and the `test-solution` run config (design D5), plus `fr task validate` producing `report.md` with no-op, oracle ×5, alternative, near-miss, pristine/historical (where applicable), upstream smoke and leak probe rows, each checked against the expected outcomes in `task.toml`. Verify on a toy external task that a deliberately wrong expected outcome fails validation.
- [ ] 5.3 Update the `evals-from-sessions` skill's `UPSTREAM.md` local changes and the task-authoring notes in `docs/` to describe the external source, claim grading and the pristine-restore labelling. Verify that the documented `fr task validate` command runs as written on the toy task.

## 6. Port batch 01

Each port: `task.toml` (upstream record, coverage tags copied from `candidates.toml`, expected outcomes), `instruction.md` from `TASK.md`, `manifest.txt` and `visible/` from the trial tree, `provenance.md` with the original host's `REPORT.md` results. Done means `fr task materialize` passes the digest check (deviations listed with their reasons), `fr task validate` matches the original control table, and one cheap real-agent smoke run finishes without an infrastructure error.

- [ ] 6.1 Port C45 (LangGraph recovery vs replay) and verify as above.
- [ ] 6.2 Port C48 (Agents SDK approval ledger, 49 claims) and verify as above.
- [ ] 6.3 Port C02 (tinygrad cache trace, 117 facts). Regenerate the ledger with `derive.py` if Podman changes values, and verify as above.
- [ ] 6.4 Port C35 (PyTorch shared symbolic row count) and verify as above, including the `torch.library.opcheck` check.
- [ ] 6.5 Port C13 (Meson CMake cache review). Verify as above, including pristine restore (behavior full, review 0/10) and the historical patch (both fail).
- [ ] 6.6 Port C04 (Tokenizers matrix DLPack). Rewrite `.cargo/config.toml` for the store mount, and verify as above, including the cold build happening inside the trial.
- [ ] 6.7 Port C37 (pybind11 3.14t ownership review) and verify as above, including the upstream probe on both interpreters. If 3.14t can't be staged, set status `hold` and record why.

## 7. Integration

- [ ] 7.1 Run a mini campaign with every ported task × one hosted and one local configuration × 3 repeats, and verify that `fr report` (or the raw results if 8.4 hasn't landed) shows claim and sub-scores with no unexplained infrastructure errors. Paid-model runs only with the user's OK.
- [ ] 7.2 Present the ported tasks with their reports at benchmark-foundation checkpoint 2 (7.8), next to the session-derived tasks, and verify the user's accept/hold decision is recorded in each task's coverage `status`.
- [ ] 7.3 Run `fr tasks grid --min 2` on the final tree, file a bead for each thin cell's best filler (C06, C08 and C36 first), and record the grid output in `CHANGELOG.md`.

## Workflow follow-up

- Archive the change after checkpoint 2 and the mini campaign are reviewed.
