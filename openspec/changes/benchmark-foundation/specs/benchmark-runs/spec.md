# Spec Delta

## Purpose

Defines what a benchmark run configuration is, how runs are executed with repeats, and how results are stored so every score can be traced back to the exact harness, model, arm and serving setup that produced it.

## ADDED Requirements

### Requirement: Run configuration identifies harness, model, arm and serving setup
A run configuration SHALL name exactly one harness (with pinned version), one model (provider and model id), one arm, one toolkit, reasoning effort, and, for local models, one serving profile. Configurations SHALL be stored as files in the repo and identified by a stable name.

#### Scenario: Complete configuration accepted
- **WHEN** a configuration names harness `codex` at a pinned version, model `openai/<id>`, arm `stock` and effort `medium`
- **THEN** the runner accepts it and records all of those values with every trial it produces

#### Scenario: Missing field rejected
- **WHEN** a configuration omits the harness version or the reasoning effort
- **THEN** the runner refuses to start and names the missing field

#### Scenario: Local model without serving profile rejected
- **WHEN** a configuration points at a local endpoint but names no serving profile
- **THEN** the runner refuses to start

### Requirement: Arm is a configuration dimension
An arm SHALL describe the instruction context given to the agent (system-prompt additions, persona text, memory files, repo instruction files). The default arm `stock` SHALL add nothing beyond the harness defaults and the task's own repo files.

#### Scenario: Same task under two arms
- **WHEN** one task is run with configurations identical except for arm `stock` versus arm `persona-x`
- **THEN** both trials are stored with their arm name and can be compared directly

### Requirement: Toolkit is a configuration dimension
A toolkit SHALL name the extra tools made available in the sandbox (CLIs such as `bd` and `openspec`, MCP servers such as codebase-memory, skills, hooks) together with any setup they need and whether the agent is told about them. The default toolkit `none` SHALL add no tools.

#### Scenario: Same task with and without tools
- **WHEN** one task is run with configurations identical except for toolkit `none` versus toolkit `dev-stack`
- **THEN** both trials are stored with their toolkit name, and only the `dev-stack` trial has the tools available

#### Scenario: Tools available but not announced
- **WHEN** a toolkit is configured to install its tools without adding their instruction text
- **THEN** the tools work in the sandbox and no instruction mentioning them is given to the agent

### Requirement: Runs execute tasks in isolated sandboxes
Each trial SHALL run in a fresh sandbox built from the task's environment, with no access to the host's home directory, session histories or credentials other than those explicitly passed for the model endpoint.

#### Scenario: Host files not visible
- **WHEN** an agent in a trial tries to list `/home/imi/.codex` or the host repo checkout
- **THEN** the path does not exist inside the sandbox

### Requirement: Repeated trials per task
The runner SHALL support running each task a configurable number of times per configuration (default 3) and SHALL report per-task and aggregate results across repeats, not just a single attempt.

#### Scenario: Three repeats reported
- **WHEN** a campaign runs 10 tasks with repeats set to 3
- **THEN** 30 trials are recorded and the report shows pass rate with its spread across repeats per task

### Requirement: Results stored with full provenance
Every trial SHALL store the full run configuration, task name and version, timestamps, the agent's native session log, a normalized trajectory, verifier output, and all score dimensions. Result directories SHALL stay local and be excluded from version control.

#### Scenario: Trace a score to its setup
- **WHEN** a user looks up any reported score
- **THEN** they can find the trial directory holding its configuration, task version, trajectory and verifier output

#### Scenario: Results never committed
- **WHEN** `git status` is run after a campaign
- **THEN** no result files appear as untracked or staged

### Requirement: Infrastructure failures are distinguished from model failures
A trial that fails because of infrastructure (build failure, sandbox error, endpoint unreachable, timeout in setup) SHALL be marked as an infrastructure error and SHALL NOT count as a model failure in scores.

#### Scenario: Endpoint down
- **WHEN** the model endpoint refuses connections for the whole trial
- **THEN** the trial is recorded as an infrastructure error and excluded from pass rate, and the report lists it separately

### Requirement: Scores are only compared within one task version
Reports SHALL group results by task version and SHALL NOT aggregate scores across different versions of the same task.

#### Scenario: Task revised mid-campaign
- **WHEN** a task is bumped from version 1.0.0 to 1.1.0 between two campaigns
- **THEN** the report shows the two versions as separate rows
