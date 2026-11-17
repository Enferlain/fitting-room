# Spec Delta

## Purpose

Defines what a benchmark task is, the task tracks supported, and the validation a task must pass before it can enter the benchmark, so scores reflect agent ability rather than broken, leaky or ambiguous tasks.

## ADDED Requirements

### Requirement: Task format
Each task SHALL be a directory with an instruction, metadata (name, version, track, difficulty, source, GPU need), an environment definition, a hidden verifier, and a reference solution. The verifier and reference solution SHALL NOT be present in the environment the agent works in.

#### Scenario: Agent cannot see tests
- **WHEN** an agent in a trial searches the filesystem for the task's verifier or solution files
- **THEN** it finds neither

### Requirement: Task tracks
Every task SHALL belong to one track: `coding` (graded by running checks against the final repo state) or `investigative` (graded by a structured answer the agent writes, or by a checklist judge when a structured answer is not possible).

#### Scenario: Investigative task with closed-set answer
- **WHEN** an investigative task asks for the root cause of a failure
- **THEN** the agent must write a JSON answer whose fields are chosen from listed options, and the verifier grades it without an LLM

#### Scenario: Investigative task with checklist
- **WHEN** an investigative task asks for an explanation that cannot be reduced to fixed options
- **THEN** the task includes a frozen checklist of 3–8 items, including at least one item penalizing invented facts, and is graded by the judge defined in trial-scoring

### Requirement: Difficulty label
Each task SHALL be labelled `discovery` (the agent must work out at least one conclusion from the repo that the instruction does not state) or `routine` (all rules are stated). Both kinds SHALL be kept. Trivial tasks, solvable by one command typed from the instruction, SHALL be rejected.

#### Scenario: Routine task kept
- **WHEN** a task states every rule and still requires applying them to real code
- **THEN** it is accepted as `routine`

### Requirement: No future history in the environment
A task environment built from a repo snapshot SHALL contain the repo at the starting commit as a single fresh commit, with no later commits, branches, tags, reflog, remotes, hooks or files from after the starting point.

#### Scenario: Leak probe
- **WHEN** the leak probe searches a built task image for strings found only in the reference solution
- **THEN** it reports zero matches and exactly one commit

### Requirement: Public upstream protection
For tasks built from repos with a public upstream (such as sd-scripts and hcom), network access during the agent phase SHALL be limited to the model endpoint and any package registries the task needs.

#### Scenario: Agent tries to fetch upstream fix
- **WHEN** an agent in an sd-scripts task tries to reach github.com
- **THEN** the connection is blocked

### Requirement: Validation before acceptance
A task SHALL enter the benchmark only after passing all of: doing nothing scores 0; the reference solution scores full marks 5 times out of 5; one near-miss solution per known failure mode scores 0; an independently written correct solution scores full marks; the leak probe is clean; one real agent run completes without infrastructure error.

#### Scenario: Flaky verifier
- **WHEN** the reference solution passes 4 of 5 times
- **THEN** the task is not accepted until the verifier is fixed

### Requirement: Human checkpoints
A task SHALL require the user's approval twice: on the candidate episode or idea before authoring, and on the finished task with its validation report before acceptance.

#### Scenario: Unattended authoring
- **WHEN** task authoring runs without the user present
- **THEN** it stops at the checkpoint and leaves a marker naming the file awaiting review

### Requirement: Versioned and frozen instruction
A task SHALL carry a version. The instruction SHALL NOT change after the first real agent run. Any later change to the verifier or environment SHALL bump the version.

#### Scenario: Verifier fix after smoke run
- **WHEN** a verifier bug is found after the first agent run
- **THEN** the fix is made in the verifier only, the version is bumped, and validation is repeated

### Requirement: GPU tasks
The task format SHALL let a task declare that it needs a GPU, with a minimum VRAM. Such tasks SHALL only be scheduled when a GPU with that much free VRAM is assigned to the trial.

#### Scenario: Not enough VRAM
- **WHEN** a GPU task needs 16 GB and the only free GPU is serving a local model with 8 GB free
- **THEN** the trial waits or is skipped with a recorded reason, and is not run on the busy GPU

### Requirement: Task privacy
Tasks built from private repos or sessions SHALL be marked private and kept in a location excluded from any published copy of this repo.

#### Scenario: Private task marked
- **WHEN** a task is built from a snapshot of a private repo
- **THEN** its metadata says `private` and it lives under the private tasks directory
