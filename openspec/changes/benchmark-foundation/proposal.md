# Proposal

## Why

Public benchmarks measure models on generic tasks, while the real question here is narrower: which model, behind which harness, handles *this* day-to-day work (on sd-scripts, pytortch-backend-experiments, data-processing, hcom and hermes-agora) well enough, and at what cost. Local models (llama.cpp today, possibly other backends later) make this more pressing, because "good enough at a fraction of the cost" can only be judged on the actual work. There are months of session history (Codex, Claude Code, Hermes, Oh My Pi) and repos with substantial test suites, so real tasks can be built from real work. Mature external pieces now exist to build on (Harbor for running agent CLIs in containers, and the `evals-from-sessions` methodology for turning sessions into verified tasks).

## What Changes

- Set up fitting-room as a Harbor-based benchmark project that runs on the local Docker backend first, with GPU access available to tasks.
- Define a **run configuration** as harness × model × arm × toolkit, plus the exact serving setup for local models. An arm is an instruction, persona or memory variant (default "stock"). A toolkit is the set of extra tools made available, such as beads, the OpenSpec CLI, the codebase-memory MCP server and skills (default "none"). Every result is tied to its full configuration.
- Provide Harbor adapters for the five harnesses in scope: Codex, Claude Code, OpenCode (Harbor built-ins, wrapped/pinned), Hermes and Oh My Pi (new custom adapters).
- Add a **session miner** that reads Codex, Claude Code, Hermes (SQLite) and Oh My Pi session stores read-only and produces a reviewable list of candidate task episodes with repo, starting commit, request, corrections and outcome signals, with secrets redacted.
- Vendor the MIT-licensed `evals-from-sessions` skill (pinned to upstream `4e85a197`) as the task-authoring procedure, extended for GPU tasks, the extra session sources, and a non-coding track.
- Support two task tracks in the first version: **coding** (graded by tests) and **investigative/Q&A** (graded by closed-set answers where possible, otherwise by a checklist judge).
- Score each trial on several dimensions: correctness, cost and tokens, wall time, tool-use behaviour, use of the provided toolkit, and process quality. The process layer uses an LLM judge from a different model family, calibrated against hand labels.
- Models in scope: GLM 5.3 and GLM 5.3 Flash (z.ai, at several reasoning efforts) and local models. GPT and Claude models are not benchmarked, to avoid cost and subscription usage; all five harnesses are driven by GLM or local models.
- Provide per-scenario local serving profiles (llama.cpp first; other backends to be explored) and a tool-calling smoke test that must pass before local-model runs are scored.
- Build a first task set of roughly 10–20 verified tasks across the priority repos.

Out of scope for this change (planned follow-ups): OpenShell sandbox backend, multi-turn tasks with a simulated user (Harbor multi-step and/or hcom), synthetic task generation at volume (bug injection, seeded-flaw tasks), persona/memory experiments beyond the arm plumbing, and dashboards.

## Capabilities

### New Capabilities

- `benchmark-runs`: run configurations (harness × model × arm × toolkit × serving setup), executing them through Harbor with repeats, and storing results with full provenance.
- `harness-adapters`: how each in-scope harness is installed, pinned, pointed at hosted or local models, and how its trajectory and usage are captured.
- `session-mining`: read-only extraction of candidate task episodes from local agent session histories.
- `task-authoring`: task format, task tracks, and the validation protocol a task must pass before entering the benchmark.
- `trial-scoring`: the score dimensions computed for every trial, the judge rules, and judge calibration.
- `local-model-serving`: serving configs for local models, recording the serving setup, GPU allocation, and the pre-run tool-calling smoke test.

### Modified Capabilities

- None (no existing specs).

## Impact

- New Python project in this repo (managed with `uv`), with Harbor as a dependency; new directories for adapters, miner, tasks, configs and results.
- New host tools: Harbor, gitleaks, OpenCode CLI (Codex, Claude Code, Hermes and Oh My Pi are already installed).
- Reads (never writes) `~/.codex/sessions`, `~/.claude/projects`, `~/.hermes/state.db` and `~/.omp/agent/sessions`.
- Uses Docker Desktop with NVIDIA GPU passthrough. The two GPUs (RTX 3090 24 GB, RTX 3080 20 GB) are shared between local model serving and GPU tasks.
- Task images contain snapshots of private repos and must never be published. Result directories may contain code and transcripts and stay local.
- GLM runs use the GLM plan's quota through the host's Agent Vault proxy (sandboxes get a placeholder key and Agent Vault's public CA, never a real key). Every run records tokens and cost.
