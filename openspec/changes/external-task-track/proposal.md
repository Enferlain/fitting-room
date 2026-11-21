# Proposal

## Why

All tasks so far are mined from the user's own sessions. On 20–21 Nov 2026 an external research pass delivered a second source (originally dropped in `docs/domain-tasks/`, now organized as `docs/external-tasks/` plus gitignored `work/domain-tasks/`):
- an audit of 48 candidate tasks on public repos (C01–C48), with scores, contamination notes and a recommended first batch;
- that first batch of seven tasks (C02, C04, C13, C35, C37, C45, C48), already authored and validated. Each has a no-op, a 5/5 oracle, an alternative solution, a near-miss and an upstream smoke run;
- a coverage tagging scheme (`tasks.toml` and `grid.py`) for seeing which pattern × domain cells the internal track leaves thin.

The batch can't run here yet. It was validated under Bubblewrap on another host (`/opt/codex/...` CPython, a seccomp filter with no network at all). Its tasks use a `TASK.md` + fixture + `answer-format.json` layout, not Harbor's `task.toml`. And their private material (oracles, expected answers, near-misses) must not reach the public remote. This change turns that material into benchmark tasks that follow the repo's existing rules: Podman store, materialized snapshots, hidden verifiers and validation before acceptance.

## What Changes

- **New external track source.** A task can come from a public upstream repo at a pinned commit, not only from a mined session. Its snapshot is materialized from a local clone of that upstream, limited to a tracked-source manifest, plus task-owned fixture files.
- **Answer grading with typed claims.** Investigative external tasks are graded by a deterministic claim grader (C02: 117 facts, C48: 49 claims, C37: 21 claims), with a pass threshold that every task declares. Mixed tasks (C13) report a behavior score and a review score separately.
- **Extra validation controls for external tasks.** The existing gates stay: no-op 0, oracle 5/5, near-miss rejected, alternative accepted, leak probe, smoke run. External tasks add an upstream smoke run, plus a pristine-restore control wherever restoring the clean upstream could repair the task. A task whose code part is fully repaired by pristine restore is labelled, and is scored only on what restore cannot give (C13's review findings).
- **Coverage tags on every task.** The `tasks.toml` fields (pattern, domains, languages, env, setup, grading, demands, evidence, contamination, status) move into each task's `task.toml` `[metadata]`. `grid.py` becomes `fr tasks grid` and reads `tasks/`. The external candidate bank keeps its own register for candidates that aren't authored yet.
- **Store components for the batch toolchains.** CPython 3.14.10 and 3.14.10t, Rust 1.100.0 with vendored crates, CMake 4.4.5 and Ninja 1.13.2, and per-task locked Python environments (PyTorch 2.15.0+cpu, NumPy 2.5.5, LangGraph, Agents SDK dependencies).
- **Port and re-validate batch 01** under Podman, then present it at the existing user checkpoint 2 next to the session-derived tasks.
- **Private evaluation material moves out of `docs/`.** Author folders, oracles, expected answers and the audit archive go to the gitignored `work/` tree (done). Only material the agent may see, or that is already public, gets tracked.

## Capabilities

### New Capabilities

- `external-tasks`: how tasks sourced from public upstream repos are pinned, materialized, graded and validated, including the pristine-restore control and the private-material boundary.
- `task-coverage`: coverage tags on every task, the candidate register, and the grid report used to choose which tasks to author next.

### Modified Capabilities

None under `openspec/specs/`, which is still empty. This change extends requirements that `benchmark-foundation` adds in `task-authoring` and that `podman-trial-environments` adds in `trial-environments`. It doesn't replace them:
- the `investigative` track gains claim-ledger grading next to closed-set and checklist answers;
- "Validation before acceptance" gains the upstream smoke and pristine-restore controls, for external tasks only;
- "Each repo uses one canonical benchmark environment" applies per external task: each one gets its own locked environment in the store.

## Impact

- `src/fitting_room/tasks/materialize.py`: an upstream source mode (clone, path manifest, overlay).
- New `src/fitting_room/tasks/coverage.py` and an `fr tasks grid` CLI command. `fr task` validation gains the extra controls.
- Store recipes for the new interpreters and toolchains. Disk cost: the PyTorch CPU environment was about 850 MiB on the validation host. The rest is small.
- `tasks/external/<id>/` for ported tasks, with snapshots gitignored.
- `work/domain-tasks/` holds the private archives. `docs/external-tasks/` holds the answer-free reference material (coverage tags, index, scores, runtime pins). Done on 2026-11-21.
- Network policy: batch 01 was validated with no network. Under Harbor the agent needs its model endpoint, so these tasks use the existing allowlist (model endpoint only). The verifier still runs without network.
