# Design

## Context

Read the proposal first for the motivation. Here is what the incoming material looks like and what the repo already has.

**Incoming material** (dropped untracked in `docs/domain-tasks/`; reorganized on 2026-11-21, see Migration Plan):

| Item | Contents | Visibility |
|---|---|---|
| `fitting-room-external-task-research.md` | Baseline research for C01–C17 (byte-identical to the copy inside the audit zip) | private: holds expected findings |
| `fitting-room-external-task-audit.zip` | `work/external-task-research/`: README with the batch recommendation, INDEX, SCORES, CONTAMINATION, per-candidate `candidate.md` / `task-draft.md` / `author.md` / `feasibility.md`, probe logs | private |
| `fitting-room-batch-01-trials.zip` | `trials/<id>/`: what the agent sees. `TASK.md` (C35 uses `README.md`), fixture, `answer-format.json`, `SNAPSHOT`, `LICENSE`, and the upstream source subset | agent-visible; upstream code is public |
| `fitting-room-batch-01-private-authoring.zip` | `author/<id>/`: `REPORT.md`, oracle, alternative, near-miss, expected answers, verifier and validator scripts, `staging.json` (per-file SHA-256 of the trial tree), `validation.json` | private |
| `fitting-room-batch-01-runtime-staging.zip` | `runtime/`: `run.sh` (Bubblewrap with a seccomp filter that blocks the network), `stage.sh`, `environment.lock` (dist-info digests per group), `requirements-*.txt` | packaging only |
| `tasks.toml`, `grid.py`, `README.md` | Coverage tags for C01–C48 (external only) and the grid report | tagging scheme |

**Validation host for batch 01:** Debian 13, CPython 3.12.14 at `/opt/codex/...` (the same path inside and outside the sandbox), GCC 14.2, uv 0.13.9. Runtime groups: `c02`, `c35` (PyTorch 2.15.0+cpu), `c04` (the c35 Python plus Rust 1.100.0 and vendored crates), `c13` (CMake 4.4.5, Ninja 1.13.2), `c37` (CPython 3.14.10 and 3.14.10t), and `c45-c48`.

**What the repo already has:**
- Harbor tasks in `tasks/<repo>/<name>/` with `task.toml`, `instruction.md`, `tests/test.sh` (which writes `/logs/verifier/reward.txt`) and `solution/`.
- Snapshots from `fr task materialize` (`git archive` of a local repo into `environment/repo/`, gitignored).
- One canonical environment per repo, set in `configs/repos/<repo>.toml` (`commit`, `python`, `sync_args`) and built into the store by `fr env ensure`.
- Validation controls run as campaigns with the `nop` and `oracle` harnesses.
- `tasks/` is tracked in git, verifiers included. `/work/` is gitignored. The remote is `github.com/Enferlain/fitting-room`.

## Goals / Non-Goals

**Goals:**
- Run batch 01 through the same `fr run` path as session-derived tasks, with results that match its validation on the original host.
- Use the original host's `staging.json` digests to check that each port is faithful.
- Make coverage a property of tasks, so the grid stays current without editing a separate file.

**Non-Goals:**
- Authoring candidates beyond batch 01. Alternates (C06, C08) and later candidates are follow-up beads.
- GPU arms (C40 on sm86, C47, C17, the C38 offload arm) and the Rust leads that need full builds (C41–C43).
- Variant generation (the controlled sibling variants in research §4). That belongs to the synthetic-task follow-up from benchmark-foundation 9.3.
- Changing how session-derived tasks are authored.

## Decisions

### D1. Task layout: tracked shell, private payload
External tasks live in `tasks/external/<id>-<slug>/` (for example `tasks/external/C45-langgraph-replay/`).

**Tracked in git:**
- `task.toml` (including coverage tags and the upstream record);
- `instruction.md`;
- `visible/` (the fixture, answer template and any staged source edits: everything the agent sees beyond upstream code);
- `manifest.txt` (the upstream paths).

**Gitignored and kept in `work/`:**
- `tests/` and `solution/`, restored by `fr task hydrate <task>` from `work/domain-tasks/private/<id>/`;
- `environment/`, materialized as usual.

Why: the audit calls oracles and expected answers private evaluation material. If they were pushed to a public remote, they could end up in future training data and invalidate the tasks. Agent-visible files are safe to track: the agent sees them anyway, and the upstream code is public.

Alternative considered: keep everything tracked, as the internal tasks do. Rejected because the internal tasks' verifiers check private code, while these verifiers would publish the answer to a public task. A second alternative, gitignoring all of `tasks/external/`, was also rejected: it would lose the coverage tags and instructions from version control.

Trade-off: the private payload has no git backup. It is copied into `work/`, and the original zips are kept next to it.

### D2. Upstream mode for `fr task materialize`
`[metadata] source = "upstream"` plus `upstream = "<url>"`, `commit = "<sha>"` and `manifest.txt` select the new mode. The upstream is cloned once into `$FR_REPOS_DIR/external/<repo>`, and fetching on the host is fine. Materialize then:
1. runs `git archive <commit> -- <manifest paths>`;
2. overlays `visible/`;
3. writes `environment/repo/` as one fresh commit, as today.

It then compares every file's SHA-256 with the expected digests stored in the task (imported from `author/<id>/staging.json`). A mismatch fails materialization and lists the files.

Why: this reuses the existing snapshot path, including the single fresh commit, `STRIP_NAMES` and the record file, and the digest check proves the port is faithful.

Alternative considered: tracking the 7 MB of upstream source subsets. Rejected because it duplicates public code in git and makes upgrades opaque.

Expected digest deviations: some trial files have to change for Podman, such as the C04 `.cargo/config.toml` mount path and anything that refers to `/opt/codex/...`. These files get a new digest recorded with the reason, and the task starts at `version = "1.0.0"` in this repo. Batch-01 validation is kept as provenance in `provenance.md`.

### D3. One canonical environment per external repo
Each external repo gets `configs/repos/<repo>.toml` with `kind = "external"`, `upstream`, `python`, and a hash-pinned `requirements` file generated from `requirements-*.txt` and `environment.lock`. `fr env ensure` builds it with uv from the host cache, the same way as today.

The code under test is never installed. `PYTHONPATH` (or a `.pth` file in the trial's working copy) points at `/work/<repo>`, and native code builds from the trial tree.

Shared groups split per repo:
- `c45-c48` becomes `langgraph` and `openai-agents`;
- `c04` reuses the PyTorch requirements set, but gets its own environment for `tokenizers`.

Why: this keeps the `trial-environments` rule of one environment per repo without a special per-task mechanism. Splitting `c45-c48` costs very little disk because uv hardlinks the packages.

New store components:
- CPython 3.12.14, unless the store's existing 3.12 differs. The interpreter version is recorded in `fitting_room.json` either way;
- CPython 3.14.10 and 3.14.10t, standalone builds;
- Rust 1.100.0, reusing the Rust component from the sd-scripts composite environment;
- CMake 4.4.5 and Ninja 1.13.2 as a `toolkit`-style binary component.

C04's crates are vendored into the store with `cargo vendor --locked --offline`, and `.cargo/config.toml` points at the read-only mount.

### D4. Verifier contract
`tests/test.sh` keeps the existing pattern: it always writes `reward.txt`, and the verifier runs with no network. Claim-graded tasks also write `/logs/verifier/claims.json` with `{passed, total, threshold, failed: [...]}`. The reward is 1 only when `passed >= threshold`.

Each task sets its threshold in `[verifier] claim_threshold`. The default is `total`, matching the audit, where C48's near-miss at 42/49 counts as rejected.

C13 writes `behavior` and `review` sub-scores to `scores.json`. Its reward requires both.

Why: Harbor needs a single reward, and the sub-scores give `fr score` / `fr report` the detail to show partial credit later without re-running anything.

Verifier scripts are ported from `author/<id>/verify.py` / `validate.py`. Paths change from `/trial` to `/work/<repo>`. The answer location is `/work/<repo>/answer.json`, as each `TASK.md` already says.

### D5. Controls as solution variants
`solution/` gains named variants: `oracle` (the default `solve.sh`), `alternative`, `near-miss`, `noop` and, where it applies, `pristine` and `historical`. A run config `test-solution` takes a `variant` field that the oracle harness applies.

`fr task validate <task>` runs this campaign:
- no-op once;
- oracle 5 times;
- every other variant once;
- `tests/upstream-smoke.sh` once;
- the leak probe.

It writes `report.md` in the existing format, with a pristine-restore row, and checks each outcome against the expected outcome declared in `task.toml`. The pristine and historical variants have an expected outcome per sub-score, not a single pass/fail. For C13, pristine restore is expected to pass behavior and score 0/10 on review.

Why: this extends the oracle-harness path the repo already uses, rather than adding a second runner. Expected outcomes are declared per task because the controls mean different things for different tasks (additive vs restore-able).

### D6. Coverage tags in `task.toml`
Tags go under `[metadata.coverage]`, using the field names and vocabularies from the incoming README. The `track` tag there means internal or external origin. It is separate from the existing `[metadata] track`, which means `coding` or `investigative`.

`fr tasks grid [--min N]` ports `grid.py` into `src/fitting_room/tasks/coverage.py` and reads:
1. every `tasks/**/task.toml`;
2. the candidate register `docs/external-tasks/candidates.toml` (tracked; tags and titles only, no answers); an entry whose id matches an authored task is skipped and reported as authored.

The two existing internal tasks (`label-busy-port`, `responsive-ctrl-c`) get tagged.

The field documentation is `docs/external-tasks/task-coverage.md`. It is safe to publish because it has no answers. `docs/external-tasks/grid.py` is removed once `fr tasks grid` replaces it.

### D7. Order of porting
1. C45 and C48 (pure Python, fake providers, about 2 s fixtures): these prove D1–D5 end to end.
2. C02 (NumPy, a 117-claim ledger).
3. C35 (PyTorch environment, about 850 MiB).
4. C13 (CMake/Ninja, the first pristine-restore control).
5. C04 (Rust build in the trial).
6. C37 (3.14t interpreters).

Every task gets a real agent smoke run with a cheap configuration (the GLM or local configs that already exist). Paid-model runs still need the user's OK.

## Risks / Trade-offs

- **[Environment drift from the validation host]** Debian glibc 2.41 vs the NixOS/Podman base image, and pip vs uv resolution, could change fixture outputs. Fixture-derived ledgers such as C02's PIDs and dispatch counts are the most sensitive. → Re-run oracle 5/5 and the alternative under Podman. If a ledger value changes, regenerate it with `derive.py` (the oracle derives the ledger from semantics, not from the host) and record the difference in `provenance.md`.
- **[3.14t support in the store]** Free-threaded standalone builds may need a different extension suffix or build flags. → C37 comes last. If 3.14t can't be staged, C37 is held. Its grading is a JSON claim ledger, so only the probe would be lost.
- **[The model endpoint opens a retrieval channel]** Batch 01 had no network at all. Now the agent can reach the model API, though nothing else. → The existing allowlist covers this. The research notes that open-network runs are a different condition. Record the network policy in each trial.
- **[Saturation]** The C45 notes warn that pending-write behavior is documented upstream. → Watch C45's pass rate in the pilot. If every configuration passes, mark it `calibration`.
- **[Private payload loss]** `work/` has no backup. → Keep the original zips in `work/domain-tasks/archive/`. `docs/external-tasks/README.md` says to back them up off-repo.
- **[Untracked zips committed by accident]** The zips are untracked today. A `git add docs/` would publish them. → Moving them is the first task, before anything else in this change is committed.

## Migration Plan

1. Move the material:
   - the zips and the research doc are copied to `work/domain-tasks/archive/` and extracted into `work/domain-tasks/private/{audit,author,trials,runtime}/`;
   - answer-free material goes to tracked `docs/external-tasks/`: README, `task-coverage.md`, `candidates.toml` (two answer-hinting notes scrubbed), `grid.py`, `index.md` and `scores.md` (links to private candidate folders stripped), `runtime/`;
   - `docs/domain-tasks/` is deleted.

   Done on 2026-11-21.
2. No running system changes. Existing tasks are only tagged, so rollback is deleting `tasks/external/` and the new repo configs.

## Open Questions

- Whether the GitHub remote is or will be public. If it is private and stays private, D1's split could later be relaxed to track `tests/`. The default stays conservative either way.
- The pass threshold for C02's 117 facts, which could be all of them or a tolerance. The default is all, matching the original validation. Revisit after pilot results.
