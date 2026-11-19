# Spec Delta

## Purpose

Defines how a trial's environment is assembled, so that adding tasks or running them in sequence costs only the tasks' own snapshots, and nothing benchmark-related is stored on C.

## ADDED Requirements

### Requirement: Heavy state is stored once
Toolchains, interpreters, dependency environments, harness installs and toolkit binaries SHALL be stored once per machine (or per repo lockfile) and shared read-only by every trial that uses them. Adding a task SHALL NOT build or copy any of them.

#### Scenario: Ten tasks of one repo
- **WHEN** ten tasks from sd-scripts whose commits share one `uv.lock` are materialized and run once each
- **THEN** one dependency environment exists for them, no image is built, and disk use outside the store grows only by the ten snapshots and the trial logs

### Requirement: Trials leave nothing behind
A trial's writes (repo edits, commits, caches, installed packages) SHALL be discarded when the trial ends. Only the trial's logs, trajectory and verifier output SHALL be kept. The task snapshot and the store SHALL be unchanged by any trial.

#### Scenario: Agent edits the repo and the env
- **WHEN** an agent modifies files under `/work/<repo>`, commits, and tries to write into the mounted dependency environment
- **THEN** the verifier in the same trial sees the modified repo, and after the trial the snapshot directory and the store's checksums are unchanged

### Requirement: Benchmark storage is off C
Images, the store, snapshots and results SHALL live on the WSL distro's disk (D:). Trials SHALL NOT use Docker Desktop.

#### Scenario: Storage check
- **WHEN** `fr doctor` (or the equivalent check) runs
- **THEN** it reports Podman's graph root, `$FR_STORE`, `tasks/` and `results/` on the WSL filesystem, and fails if any of them is under `/mnt/c`

### Requirement: Exact dependencies per task commit
A Python task's environment SHALL be synced from the `uv.lock` at the task's `start_commit`, not from another commit's lockfile. The environment key and interpreter version SHALL be recorded in the trial's `fitting_room.json`.

#### Scenario: Two commits with different locks
- **WHEN** two tasks of the same repo have different `uv.lock` contents at their start commits
- **THEN** they run against two different environments, each matching its own lockfile, and both keys appear in their trials' records

### Requirement: GPU access and pinning under Podman
A GPU task SHALL get the WSL GPU device and driver libraries, with `CUDA_VISIBLE_DEVICES` set to the campaign's task GPU UUID. Non-GPU tasks SHALL get no GPU device.

#### Scenario: GPU task on the 3080
- **WHEN** a GPU task runs with the task GPU set to the 3080's UUID
- **THEN** `torch.cuda.device_count()` is 1 and the device is the RTX 3080, and a CPU task in the same campaign has no `/dev/dxg`

### Requirement: Same network behaviour as before
Agents SHALL reach GLM through Agent Vault with only a placeholder key and Agent Vault's public CA, reach the benchmark llama-swap on the host, and be restricted by Harbor's allowlist mode where a task sets it.

#### Scenario: Allowlisted task
- **WHEN** a task with `network_mode = "allowlist"` (model endpoint only) runs and the agent tries `github.com`
- **THEN** the request is blocked while the model endpoint works, and the trial is not an infrastructure error
