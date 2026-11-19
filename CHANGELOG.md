# Changelog

Landed progress, newest first. Planning lives in `openspec/changes/benchmark-foundation/`; task status in its `tasks.md`.

## 2026-11-19

### Changed
- Repo images no longer carry the uv cache (it doubled every Python image: sd-scripts 29 → 12.3 GB, pytortch 39 → 19 GB) or `COPY warm/` layers; builds use a BuildKit cache mount and bind mounts. fitting-room images and build cache went from about 170 GB to 35 GB.

### Added
- Campaign-level `agent_timeout_multiplier` for extending agent execution. The generated Harbor job config records the multiplier.
- Interpreter-specific tags for historical Python images built with `FR_IMAGE_PYTHON`.
- Vendored `evals-from-sessions` 1.0.4 (upstream `4e85a197`, MIT) into `.agents/skills/evals-from-sessions/` with a `.claude/skills` symlink; unmodified copy committed first and checked against upstream by SHA-256. Local overrides (candidates from `fr triage`, three grading routes including judge-graded tasks, web access, repo tools, GPU tasks, GLM/local smoke runs) are listed in its `UPSTREAM.md`.
- `fr task materialize <task>`: writes `environment/repo/` as `git archive` of the task's repo at `start_commit`, without `.env`-style files or outward symlinks.

- Toolkits: `dev-stack` (bd, openspec, codebase-memory MCP + skill) staged per run onto hardlinked task copies; MCP and skills registered through Harbor's agent config; harness/item support table refuses unsupported items. omp gets omp-native MCP config.
- Images (`images/`): a CPU base (git, uv, Node; build jobs capped), per-repo images with toolchains and warmed dependencies (`images/build.sh <repo>`), and a `dev-stack` toolkit layer (bd 1.3.2, openspec 1.15.0, the user's codebase-memory fork built static) that is off unless a run enables it. Task repos live at `/work/<repo>`. Per-repo snapshot excludes (`configs/repos/`), used for pytortch's 16k generated stage5 artifacts.

### Verified
- `dev-stack` toolkit smoke (`spikes/toolkit-check`): Claude Code, omp and Hermes with GLM and Hermes with Qwen3.5-9B pass with real codebase-memory MCP calls; OpenCode and Codex register the server but Qwen3.5-9B does not call its tools (to re-check with a stronger local model); toolkit `none` leaves bd/openspec absent.
- Repo test suites in their images with the network off: data-processing and hermes-agora all green; hcom 2,615/2,616 (one host temp-dir test); sd-scripts with the 3080 2,577 passed vs 2,569 on the host checkout; pytortch on the 3080 626 passed, 7 failed (retired stage5 equivalence needing a host-only binary).
- dev-stack layer on a data-processing snapshot: one clean commit, bd shows the snapshot's issues, openspec runs, codebase-memory index ready.
- Leak probe on a materialized data-processing snapshot: one commit, no remotes/tags/hooks, no strings from later commits.

## 2026-11-18

### Added
- `fr triage`: GLM (max thinking) writes a stand-alone task statement, work type, size, grading route, GPU need and verdict for mined episodes, always covering recent work. Checkpoint 1: 40 candidates selected (`work/mining/selected.md`).
- Miner attributes an episode to the repo its edits landed in, and reads an archive copy of Claude transcripts (`~/.local/share/claude-transcript-archive`).
- Pair `codex` × `local` using Harbor's built-in Codex agent against llama-server's Responses API. `fr run` never passes the variables that would make Harbor upload the host Codex login.

### Verified
- Hermes + GLM 5.3 Flash passed the hello task through `fr run smoke-hermes-glm`. GLM 5.3 Flash may skip reasoning on trivial steps even with thinking on (direct API check agrees).
- Follow-up relabel with v3 finished: 3,354 of 3,360 follow-ups labelled; 655 agent shortfalls over 465 episodes. Candidate ranking rebuilt and now shows shortfall kinds.
- Codex 0.163.0 + local Qwen3.5-9B passed the hello task through `fr run smoke-codex`, with ATIF and token usage.

## 2026-11-17

### Added
- Hermes adapter (`fitting_room.adapters.hermes:FrHermes`): thin subclass of Harbor's `hermes` agent pinned by commit (`v2026.9.24`), installer from the pinned commit without browser extras (~6 min instead of 14+), required reasoning level (never off), and token counts from the session export. Pairs `hermes` × `zai` and `hermes` × `local` enabled; local placeholder key is now `no-key-required`.
- `uv` project with Harbor 0.26.0 pinned, `fr` CLI, pytest and ruff.
- Run configurations and campaigns (`configs/runs/`, `configs/campaigns/`) with up-front validation; `fr run <campaign>` runs one Harbor job per configuration, writes a provenance sidecar (`fitting_room.json`) into every trial, and reports pass / fail / infrastructure errors (infrastructure errors excluded from pass rate). See `docs/running.md`.
- Providers `zai` (GLM through Agent Vault, placeholder key, CA overlay generated per job) and `local` (serving profile, endpoint checked before running); harness × provider pairs are allowed only after a passing smoke run.
- `fr classify`: labels mined follow-ups with GLM 5.3 Flash (thinking on, via Agent Vault) as model_error / misunderstanding / scope_change / question / acknowledgement, using the assistant message before and after as context; labels are cached and `fr mine` ranks candidates by model errors (keyword heuristic as fallback). Pilot: 40 follow-ups, 5 calls.
- `fr reviews`: extracts review passes with what happened next (agent reply, edits, test runs) into `work/mining/reviews.jsonl`: review-mcp results from Codex (direct calls, code-mode `exec`, and async cells resolved through `wait`) and Claude Code review/audit/verify agents (background hand-backs included). Failed reviews (timeouts, quota errors) are excluded. Priority repos: 619 usable reviews, 412 followed by edits.
- `fr label-reviews`: GLM labels each extracted review real_bug_fixed / real_bug_unfixed / false_positive / minor_only / no_findings with a one-line bug summary. Result over 618 reviews: 154 real bugs fixed, 106 real bugs unfixed, 34 false positives. `fr mine` attaches confirmed review bugs to the episode they happened in (178 episodes) and ranks them first.
- `fr calibrate sample|score`: blind yes/no/unclear check of GLM's follow-up labels; first 50-item sample written.
- Oh My Pi adapter (`fitting_room.adapters.omp:OhMyPi`): thin subclass of Harbor's Pi agent using Bun and the `@oh-my-pi/pi-coding-agent` npm package; pair `omp` × `zai` enabled.
- Local serving: `fr serve up|down <profile>` launches a standalone llama-swap profile on `127.0.0.1:18080` (Windows binaries via PowerShell, real PID tracked); first profile `qwen35-9b-3080` (Qwen3.5-9B on the RTX 3080).
- Session miner: `fr mine --repo <name>...` reads Codex, Claude Code, Hermes (read-only SQLite) and Oh My Pi histories, splits sessions into episodes (substantive request + follow-ups, with corrections flagged), recovers the starting commit (from Codex metadata or inferred from git history), counts edits / test runs / commits, redacts secrets (gitleaks + regex) and writes `work/mining/candidates.md` (top 40 per repo, ranked), `candidates-all.md` and `candidates.jsonl`. Handles Codex's VS Code wrapper and code-mode `exec` patches.
- Spike tasks in `spikes/` and findings in `docs/spikes.md`; harness notes in `docs/harnesses.md`.

### Verified
- Hermes 2026.9.24 + local Qwen3.5-9B passed the hello task through `fr run smoke-hermes` with ATIF and token usage. Hermes + GLM not run yet.
- Follow-up labeller calibration (50 items, 27 with yes/no answers after re-checking 3 against full sessions): prompt v3 at max thinking 89% agreement, κ 0.77; v1 81%, κ 0.64. v3 adopted; relabelling all follow-ups with it.
- z.ai throttles concurrent requests on the GLM Coding Lite plan: 4+3 concurrent calls returned persistent 429s at 1% quota; 2 concurrent in total runs clean.
- Oh My Pi 18.12.6 + GLM 5.3 Flash passed the hello task through `fr run smoke-omp`, with an ATIF trajectory including tool calls.
- `fr run smoke-real`: Claude Code + GLM 5.3 Flash and OpenCode + local Qwen3.5-9B both passed the hello task end to end.
- Mining the five priority repos: 712 sessions read, 3,883 episodes (1,237 coding), 11 secrets redacted, output kept out of git.
- Harbor on Docker Desktop/WSL2: hello task (oracle 1, nop 0); agent-phase network allowlist; sandboxes reach host services on `127.0.0.1` via `host.docker.internal`.
- GPUs cannot be isolated on Docker Desktop/WSL2; pinning works with `CUDA_VISIBLE_DEVICES=<uuid>` (soft pin).
- OpenCode 2.2.6 + local Qwen3.5-9B solved the hello task; Claude Code 2.1.263 + GLM 5.3 Flash (through Agent Vault, placeholder key) solved it too.

### Decided
- Models benchmarked: GLM 5.3 / GLM 5.3 Flash and local models; GPT and Claude models are not benchmarked (they may still serve as the LLM judge).
- Local backends beyond llama.cpp to be explored (beads `fitting-room-kap.1`).
