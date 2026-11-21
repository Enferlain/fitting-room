# Spec Delta

## Purpose

Defines how benchmark tasks built on public upstream repositories are pinned, staged, graded and validated, so they measure the agent rather than its ability to recover a public fix or read private answers.

## ADDED Requirements

### Requirement: Pinned upstream source
An external task SHALL record its upstream repository, the full commit hash, and a tracked-source manifest of the paths the trial receives. Materializing the task twice from the same record SHALL produce byte-identical snapshots.

#### Scenario: Re-materialize
- **WHEN** an external task is materialized, deleted, and materialized again from the same upstream clone
- **THEN** the two snapshots have identical per-file SHA-256 digests, and those digests match the task's recorded staging digests

#### Scenario: Commit not available
- **WHEN** the local upstream clone does not contain the recorded commit
- **THEN** materialization fails and names the repository and commit, and it does not fall back to another revision

### Requirement: Snapshot contains only declared paths
An external task's snapshot SHALL hold only the manifest paths from upstream plus the task's declared visible files (instruction, fixtures, answer template, licence). It SHALL NOT hold version-control data, upstream history or files outside the manifest.

#### Scenario: Partial monorepo snapshot
- **WHEN** a task's manifest lists only `libs/langgraph` and `libs/checkpoint` from the LangGraph monorepo
- **THEN** the snapshot holds those trees, the fixture, `TASK.md`, `answer-format.json` and `LICENSE`, and nothing else from upstream

### Requirement: No pristine copy of the code under test
The trial SHALL NOT expose any installed, cached or prebuilt copy of the repository under test: no wheel or sdist, editable install, Cargo checkout or native library. Third-party dependencies MAY come from the store. The code under test SHALL load or build from the snapshot.

#### Scenario: Import resolution
- **WHEN** a trial for a task on tinygrad runs `python -c "import tinygrad; print(tinygrad.__file__)"`
- **THEN** the printed path is inside the trial's working copy of the snapshot

#### Scenario: Native rebuild
- **WHEN** a Tokenizers task is verified
- **THEN** the extension the verifier imports was compiled during that trial from the trial tree, not taken from the store or a cache

### Requirement: Private evaluation material is never agent-visible
Oracles, expected answers, near-miss and alternative solutions, author notes, probes and the candidate research SHALL stay out of the trial environment and out of tracked files. They SHALL live in the gitignored local workspace.

#### Scenario: Agent searches for answers
- **WHEN** an agent in an external trial searches the filesystem for the task's expected answer or oracle
- **THEN** it finds neither

#### Scenario: Repository check
- **WHEN** `git ls-files` is run in fitting-room
- **THEN** no oracle, expected answer, near-miss, alternative, or audit archive for an external task is listed

### Requirement: Agent network limited to the model endpoint
During an external task's agent phase, network access SHALL be limited to the model endpoint. The verifier phase SHALL run with no network access.

#### Scenario: Agent tries to fetch upstream
- **WHEN** an agent in a C45 trial tries to reach github.com or pypi.org
- **THEN** the connection is blocked and the model endpoint is still reachable

### Requirement: Claim-ledger grading
An investigative external task MAY be graded by a deterministic claim grader. The grader checks typed claims in the agent's JSON answer against a frozen reference, with no LLM involved. It SHALL report claims passed out of claims total, and the task SHALL declare the pass threshold.

#### Scenario: Partial answer
- **WHEN** a C48 answer gets 42 of 49 claims right and the task's threshold is all 49
- **THEN** the trial is recorded as failed, with the claim score 42/49 and the identifiers of the failed claims

#### Scenario: Malformed answer
- **WHEN** `answer.json` is missing or doesn't match `answer-format.json`
- **THEN** the claim score is 0 and the verifier output says the answer was missing or malformed

### Requirement: Separate behavior and review scores
A task that asks for both a code change and a review disposition SHALL report the behavior score and the review score separately. Neither score SHALL be folded into the other.

#### Scenario: Pristine restore on a review task
- **WHEN** C13's tracked code is restored to clean upstream and no review answer is written
- **THEN** the behavior score is full and the review score is 0/10

### Requirement: External validation controls
An external task SHALL pass the general acceptance gates under the trial environment it will be benchmarked in. It SHALL also record an upstream smoke run, which shows that the unmodified upstream code works in that environment.

#### Scenario: Port from another host
- **WHEN** a batch-01 task validated on the Bubblewrap host is ported to Podman
- **THEN** no-op, oracle 5/5, alternative, near-miss and upstream smoke are all re-run under Podman and written to the task's report, and earlier results from the other host count only as provenance

### Requirement: Pristine-restore control
An external task with staged changes to upstream code SHALL run a pristine-restore control and record which scores the restore earns. A task whose restore earns the full primary score SHALL be labelled `calibration`. It SHALL NOT be used for primary discrimination unless the task has an independent contract that restore cannot satisfy.

#### Scenario: Restore repairs core behavior
- **WHEN** restoring C01's clean upstream files makes its behavior tests pass
- **THEN** the task is labelled `calibration` and the report says restore suffices

#### Scenario: Additive task
- **WHEN** a task adds a new contract to unmodified upstream (for example C04's batch DLPack export)
- **THEN** the pristine-restore control is recorded as not applicable, and the unmodified pin serves as the no-op
