# Spec Delta

## Purpose

Defines how local models are served for benchmark runs so that results are reproducible, the serving setup is recorded, GPU use does not collide with GPU tasks, and a broken tool-calling setup is never mistaken for a weak model.

## ADDED Requirements

### Requirement: Serving profiles
Each local model setup SHALL be described by a named serving profile, kept as a readable file in this repo, that fully specifies: server binary and version, model file and quantization, chat template, tool-call handling, sampling settings, context size, parallel slots, and which GPU(s) it uses.

#### Scenario: Profile referenced by a run
- **WHEN** a run configuration names serving profile `qwen-coder-q6-3090`
- **THEN** the trial record includes every field of that profile

### Requirement: Benchmark serving is separate from daily serving
Benchmark serving profiles SHALL be stored and launched separately from the user's everyday llama-swap configuration and SHALL NOT modify it.

#### Scenario: Everyday config untouched
- **WHEN** a benchmark campaign starts and stops its local server
- **THEN** the user's everyday llama-swap configuration file is unchanged

### Requirement: Endpoint reachable from sandboxes
A local model server used in a run SHALL be reachable from inside task sandboxes on a known address, without opening it to other hosts.

#### Scenario: Agent reaches local model
- **WHEN** an agent inside a task sandbox calls the configured local endpoint
- **THEN** the call reaches the benchmark's local server

### Requirement: Tool-calling smoke test gates scoring
Before any scored trial uses a serving profile with a given harness, a smoke test SHALL check that the harness can make a tool call through that endpoint and receive the result. If it fails, scored trials for that pair SHALL NOT run.

#### Scenario: Parser misconfigured
- **WHEN** the server returns tool calls as plain text instead of structured calls
- **THEN** the smoke test fails, the campaign skips that harness and profile, and the report states why

### Requirement: GPU allocation is explicit
Each campaign SHALL declare which GPU serves the local model and which GPU is available to GPU tasks, and SHALL NOT schedule a GPU task on a GPU that is serving a model unless the task's declared VRAM fits in what remains.

#### Scenario: Split across two GPUs
- **WHEN** a campaign serves the local model on one GPU and runs sd-scripts GPU tasks
- **THEN** the GPU tasks run on the other GPU
