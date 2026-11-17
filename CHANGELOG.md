# Changelog

Landed progress, newest first. Planning lives in `openspec/changes/benchmark-foundation/`; task status in its `tasks.md`.

## 2026-11-17

### Added
- `uv` project with Harbor 0.26.0 pinned, `fr` CLI, pytest and ruff.
- Run configurations and campaigns (`configs/runs/`, `configs/campaigns/`) with up-front validation; `fr run <campaign>` runs one Harbor job per configuration, writes a provenance sidecar (`fitting_room.json`) into every trial, and reports pass / fail / infrastructure errors (infrastructure errors excluded from pass rate). See `docs/running.md`.
- Providers `zai` (GLM through Agent Vault, placeholder key, CA overlay generated per job) and `local` (serving profile, endpoint checked before running); harness × provider pairs are allowed only after a passing smoke run.
- Local serving: `fr serve up|down <profile>` launches a standalone llama-swap profile on `127.0.0.1:18080` (Windows binaries via PowerShell, real PID tracked); first profile `qwen35-9b-3080` (Qwen3.5-9B on the RTX 3080).
- Session miner: `fr mine --repo <name>...` reads Codex, Claude Code, Hermes (read-only SQLite) and Oh My Pi histories, splits sessions into episodes (substantive request + follow-ups, with corrections flagged), recovers the starting commit (from Codex metadata or inferred from git history), counts edits / test runs / commits, redacts secrets (gitleaks + regex) and writes `work/mining/candidates.md` (top 40 per repo, ranked), `candidates-all.md` and `candidates.jsonl`. Handles Codex's VS Code wrapper and code-mode `exec` patches.
- Spike tasks in `spikes/` and findings in `docs/spikes.md`; harness notes in `docs/harnesses.md`.

### Verified
- `fr run smoke-real`: Claude Code + GLM 5.3 Flash and OpenCode + local Qwen3.5-9B both passed the hello task end to end.
- Mining the five priority repos: 712 sessions read, 3,883 episodes (1,237 coding), 11 secrets redacted, output kept out of git.
- Harbor on Docker Desktop/WSL2: hello task (oracle 1, nop 0); agent-phase network allowlist; sandboxes reach host services on `127.0.0.1` via `host.docker.internal`.
- GPUs cannot be isolated on Docker Desktop/WSL2; pinning works with `CUDA_VISIBLE_DEVICES=<uuid>` (soft pin).
- OpenCode 2.2.6 + local Qwen3.5-9B solved the hello task; Claude Code 2.1.263 + GLM 5.3 Flash (through Agent Vault, placeholder key) solved it too.

### Decided
- Models benchmarked: GLM 5.3 / GLM 5.3 Flash and local models; GPT and Claude models are not benchmarked (they may still serve as the LLM judge).
- Local backends beyond llama.cpp to be explored (beads `fitting-room-kap.1`).
