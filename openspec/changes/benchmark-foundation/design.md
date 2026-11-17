# Design

## Context

Greenfield repo (only beads and OpenSpec scaffolding exist). See proposal.md for motivation and specs/ for required behaviour. Research backing these choices is in `docs/` (framework comparison and the Q2–Q9 notes).

Host facts that shape the design (checked 2026-11-17):

- NixOS-WSL2 with mirrored networking. Docker Desktop 29.9 works; OpenShell's Docker driver does not (seccomp under mirrored mode), and its microVM driver is qualified but has no running gateway.
- GPUs: RTX 3090 (24 GB) and RTX 3080 (20 GB).
- Installed: `uv`, `codex`, `claude`, `hermes`, `omp`. Not installed: Harbor, gitleaks, OpenCode.
- Session stores: Codex JSONL (records git commit per session), Claude Code JSONL (branch and time, no commit), Hermes SQLite `state.db` (`sessions` and `messages` tables, with cwd, branch, model and cost), Oh My Pi JSONL under `~/.omp/agent/sessions` (63 files).
- The everyday llama-swap normally listens on `:8080`. Its config location is `D:\textgen\2026\llama-swap`. It was not running when checked.
- Priority repos have large test suites: sd-scripts, pytortch-backend-experiments, data-processing, hcom (Rust). hermes-agora has few tests. sd-scripts and hcom have public upstreams.

## Goals / Non-Goals

**Goals:**
- One command path from "session history" to "verified task" to "multi-dimension comparison across configurations".
- Every score reproducible from stored configuration and artifacts. Scoring can be re-run on stored trials without re-running agents.
- Adding a harness, arm, toolkit or serving profile is a config or adapter change, not a runner change.

**Non-Goals:**
- Writing our own sandbox runner or task format (Harbor's is used as is).
- Leaderboards, dashboards, or publishing tasks.
- Hosting or scaling beyond this one machine.

## Decisions

### D1. Harbor as the runner, installed as a project dependency
Harbor (pinned version in `pyproject.toml`, managed by `uv`) runs trials, builds environments, runs verifiers and writes job directories. Custom agents load by import path (`-a fitting_room.adapters.hermes:HermesAgent`), so Harbor must live in the same environment as our package. A global `uv tool install` would not see our modules.
*Alternatives:* Inspect AI + inspect_swe (easier local-model proxying, but weak multi-turn support and Python-defined tasks); own runner (most work, no ecosystem). Harbor wins on adapter coverage, file-based tasks, multi-step and simulated-user support for the planned follow-up, the ATIF trajectory format, and compatibility with `evals-from-sessions`.

### D2. Docker backend now, OpenShell later behind the same interface
Use Harbor's built-in Docker environment. OpenShell becomes a `BaseEnvironment` subclass in a follow-up change. Risk-reduction spikes come first (task 2): GPU passthrough via `--gpus`, network allowlist enforcement, and `host.docker.internal` reachability in Harbor's Docker environment. If Harbor's Docker environment lacks a needed feature, we subclass it rather than fork Harbor.

### D3. Repo layout
```
pyproject.toml                 # uv project; harbor pinned
src/fitting_room/
  adapters/                    # harness adapters (D5)
  miner/                       # session miner (D7)
  scoring/                     # metrics + judge + calibration (D9, D10)
  serving/                     # serving-profile launcher + smoke test (D11)
  cli.py                       # `fr` entry point
configs/
  runs/<name>.toml             # one run configuration each
  campaigns/<name>.toml        # configs × task selection × repeats
  arms/<name>/                 # arm content (D6)
  toolkits/<name>/             # toolkit definition (D13)
  serving/<name>.yaml          # standalone llama-swap config per scenario
  prices.toml                  # per-model token prices for hosted models
images/<repo>/Dockerfile       # per-repo base images (D8)
tasks/<repo>/<task>/           # task definitions (repo snapshot NOT committed)
.agents/skills/evals-from-sessions/   # vendored skill (D12); .claude/skills symlink
work/                          # gitignored: mining output, materialized snapshots
results/                       # gitignored: Harbor job dirs + scores
```
CLI: `fr mine`, `fr task materialize`, `fr serve up|down|smoke`, `fr run <campaign>`, `fr score`, `fr judge`, `fr label`, `fr report`.

### D4. Run configuration and campaigns as TOML
A run config holds harness, harness version, model, endpoint or serving profile, arm, toolkit and effort (spec: benchmark-runs). A campaign lists run configs, a task selector (by repo, track or tag) and repeats (default 3). `fr run` validates every config before starting anything, starts the serving profile if needed, runs the smoke gate, then calls Harbor once per config with `-k <repeats>`. Each trial's `result.json` is extended with a `fitting_room.json` sidecar holding the resolved config, serving profile, arm digest and toolkit digest.

### D5. Harness adapters
| Harness | Basis | Notes |
|---|---|---|
| Codex | Harbor `codex` built-in, thin subclass | pins version; clean `CODEX_HOME`; local models need llama-server's Responses API (smoke-tested) |
| Claude Code | Harbor `claude-code` built-in, thin subclass | pins version; for local models sets base URL and maps all model tiers to the local model, and disables nonessential traffic so background calls do not hit a single-slot server |
| OpenCode | Harbor `opencode` built-in, thin subclass | openai-compatible provider config generated per run |
| Oh My Pi | thin subclass of Harbor's built-in `pi` agent | omp is a Pi fork; override install (pinned omp build) and binary/session paths |
| Hermes | thin subclass of Harbor's built-in `hermes` agent | Hermes has a one-shot mode (`-z`) and writes a usage report (`--usage-file`). Spike (task 4.1) checks that the installed Hermes matches the host build. Usage comes from that report, with the in-container `state.db` as a fallback |

Models and credentials: benchmark runs use **GLM 5.3 and GLM 5.3 Flash** (z.ai, at several reasoning efforts) and **local models**. GPT and Claude models are not benchmarked (cost and usage). All five harnesses are driven by these models (for example Claude Code against z.ai's Anthropic-compatible endpoint). No real key enters a sandbox: the agent gets a placeholder key, and the host's Agent Vault (a Windows MITM proxy) substitutes the real key in-flight for `api.z.ai`. Containers already resolve `api.z.ai` to Agent Vault's FakeIP range through Docker Desktop's host DNS forwarding (checked 2026-11-17). The only addition is trusting Agent Vault's **public** root CA inside the sandbox: a run-level Compose overlay mounts the CA certificate and sets `NODE_EXTRA_CA_CERTS`, `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE`, using a combined system + Agent Vault bundle for the latter two. Local models use a placeholder key as well, since llama.cpp ignores it.

All adapters start from an empty harness home, so no host config, memories, skills, hooks or MCP servers leak in (spec: harness-adapters). Normalized trajectory = Harbor's ATIF. Built-ins already emit it; the two new adapters convert their native logs to ATIF. When conversion is incomplete, the native log is still stored and the missing metrics are marked unknown.

### D6. Arms as harness-neutral content mapped per harness
`configs/arms/<name>/` may contain `system_append.md`, `instructions.md` (AGENTS.md/CLAUDE.md-style), and `memory/`. Each adapter maps these to its own surface (Claude Code `--append-system-prompt`, Codex `developer_instructions`, and the equivalents for the others). The mapping and the resulting placement (system versus user message) are recorded per trial, because placement is a known confound. Only `stock` (empty) is required in this change. Persona and memory arms come in a follow-up.

### D7. Session miner: per-source readers, one candidate schema
Stdlib Python. One reader per source (Codex JSONL, Claude JSONL, Hermes SQLite opened with `mode=ro`, omp JSONL) yields episodes into one record type (spec: session-mining). Commit inference for Claude/omp/Hermes uses `git rev-list -1 --before=<start> <branch>` in the local repo. Subagent detection: Codex `thread_source == "subagent"`, Claude `subagents/` paths, Hermes `parent_session_id`. Output goes to `work/mining/candidates.{md,jsonl}`, scanned with gitleaks and redacted before writing (regex fallback if gitleaks is missing, with a warning). The miner does not judge task quality beyond a heuristic track suggestion: selection is the human checkpoint.

### D8. Per-repo base images, snapshots materialized at run time
Heavy repos (sd-scripts, the PyTorch backend) get a shared base image with dependencies and CUDA, built once in `images/<repo>/`. Each task's Dockerfile is `FROM` that base and copies `environment/repo/`. `environment/repo/` is produced by `fr task materialize` (`git archive <commit>` from the local repo, using the source repo and commit recorded in `task.toml`) and is gitignored. This keeps private code and large snapshots out of git, and lets tasks be rebuilt exactly. Dependency drift between the base image and a task's commit is caught by validation (the oracle must pass 5/5).

### D9. Deterministic scoring as a separate pass over stored trials
`fr score` reads each trial's ATIF, native log and verifier output and writes `scores.json` with the measured dimensions (spec: trial-scoring). Cost comes from provider-reported cost when present, otherwise tokens × `configs/prices.toml`. Local models record tokens and time with dollar cost 0. "Verified before finishing" = the last test-runner invocation comes after the last file-modifying tool call. Test-runner commands are recognized per repo (`pytest`, `cargo test`, …) from task metadata. Toolkit usage (D13) is computed in the same pass by classifying each tool call against the trial's toolkit.

### D10. Judge and calibration
`fr judge` runs a pinned judge (model, prompt and criteria versioned together as `judge-vN`) on stored trials. It picks a judge from a different family than the agent, fixed per judge version. Because the benchmarked models are GLM and local models, a GPT or Claude judge is from a different family for every agent, which removes self-preference from the pairing. Judging is far smaller than benchmarking (one call per trial), so the judge does not need to be one of the benchmarked models. GLM or a strong local model of another family remain fallbacks. Input is the instruction, diff or answer, verifier output and the ATIF tool calls with the final message stripped. The report-honesty criterion is the only one that gets the final message. Criteria are yes/no.
`fr label` gives the user a terminal form over a sample of trials to answer the same criteria. Validation threshold: ≥80% raw agreement and Cohen's κ ≥ 0.6 per dimension over ≥30 labelled trials. Below that, the dimension shows as unvalidated.

### D11. Local serving profiles as standalone llama-swap configs
Each `configs/serving/<name>.yaml` is a self-contained llama-swap config (one or a few models) with fixed server flags (for llama.cpp: `--jinja`, template, parallel slots, context, sampling) and the GPU pinned by UUID. `fr serve up` launches it on a dedicated port (default `18080`, never `8080`), leaving the everyday llama-swap alone. On this host llama-swap and llama-server are Windows binaries, launched through PowerShell so the real Windows PID can be recorded and only that process tree is stopped. Sandboxes reach it via `host.docker.internal:18080`. Default GPU split: model on the 3090, GPU tasks on the 3080, overridable per campaign. The first profile (`qwen35-9b-3080`) puts a small model on the 3080 for harness smoke tests.

Profiles are meant to be backend-agnostic: local models may run on backends other than llama.cpp. Whether llama-swap can front those (its model `cmd` launches an arbitrary server) and how health checks, ports and unloading then behave is unexplored (beads `fitting-room-kap.1`). Until then only llama.cpp profiles are supported, and each profile records its backend and version. The smoke gate runs the harness itself against a one-tool task in Harbor, not a raw API call, so harness-side parser problems are caught too.

### D12. Vendored evals-from-sessions skill
Copy upstream `4e85a197` into `.agents/skills/evals-from-sessions/` (symlinked from `.claude/skills/`), keeping LICENSE and adding `UPSTREAM.md` (source URL, commit, list of local changes). Local changes: session table adds Hermes and omp, a pointer to `fr mine` output as the candidate source, GPU tasks allowed (with `gpu_vram_gb` metadata) instead of rejected, the investigative-checklist track, and `fr task materialize` replacing committed snapshots.

### D13. Toolkits: separate from arms, declared per item
A toolkit varies independently of the arm, so "same persona, with and without tools" and "tools announced versus only present" are both expressible. `configs/toolkits/<name>/toolkit.toml` lists items, each with:
- **kind:** `cli`, `mcp`, `skill` or `hook`;
- **install step:** run when the image is built, e.g. installing `bd` and `openspec`, or installing codebase-memory and indexing `/app` so the graph matches the snapshot;
- **runtime setup:** e.g. `bd init` in the repo;
- **announce text:** optional, e.g. a beads/OpenSpec instruction section, added through the arm mechanism only when `announce = true`;
- **usage matchers:** MCP server name, skill name, or shell binary prefix such as `bd ` or `openspec `;
- **checks:** optional, e.g. a beads issue was created and closed, or `openspec validate` was run.

Adapters register MCP servers and skills in the harness's own config inside the clean harness home. A configuration whose toolkit has an item the harness can't support is refused (spec: harness-adapters). Only `none` and one `dev-stack` toolkit (bd, openspec, codebase-memory MCP, the repo's skills) are required in this change. Toolkit setup that writes into the repo (such as `.beads/`) happens before the agent starts and is excluded from the agent's diff when scope is judged.

## Risks / Trade-offs

- [Harbor's Docker environment may not support GPU or allowlist networking as needed] → spike in task 2 before building on it. Fallback is a `DockerEnvironment` subclass.
- [Harbor churn (pre-1.0 APIs)] → pin the version. Upgrades are deliberate and re-validate tasks.
- [Hermes may lack a clean headless mode or container install] → spike first. If blocked, Hermes runs host-side in a `BaseAgent` that acts through `environment.exec`, which isolates tools but not the harness process (recorded as a limitation).
- [Low task yield from history, as the papers report about 1%] → accept 10–20 tasks for this change. Volume generation is a follow-up.
- [The judge is unreliable on trajectories (research: fooled by confident closings)] → strip final messages, yes/no criteria, calibration gate, unvalidated marking.
- [Silent tool-call failures with local models look like weak models] → smoke gate plus serving profile recorded per trial.
- [Large CUDA base images and slow builds] → per-repo base images, built once and cached.
- [VRAM contention between serving and GPU tasks] → explicit GPU split per campaign. Docker Desktop on WSL2 cannot isolate GPUs (spike 2.2), so the task GPU is pinned with `CUDA_VISIBLE_DEVICES=<uuid>` through a run-level Compose overlay. This is a soft pin an agent could undo, recorded as a known limitation.
- [Private code goes to hosted model APIs during runs] → accepted for z.ai (GLM), matching existing daily use. Results and tasks stay local and gitignored.
- [Agent Vault is down or locked, so GLM calls fail inside sandboxes] → these surface as connection or auth errors, which are classified as infrastructure errors and excluded from scores. A pre-campaign check calls the endpoint once before starting.
- [Some harnesses may not speak a protocol z.ai offers (e.g. Codex requires the Responses API)] → the smoke gate refuses that harness × endpoint pair with a recorded reason, rather than scoring failures.
- [Public-upstream tasks could be solved by fetching upstream] → agent-phase allowlist (model endpoint and registries only).
- [Toolkit setup changes the repo or the task's difficulty, e.g. an index that answers questions directly] → toolkit setup is recorded per trial, and toolkit and no-toolkit results are never pooled in one row.

## Migration Plan

Greenfield, no migration. Rollback means deleting the new directories. Nothing outside this repo is modified: session stores are read-only, and the everyday llama-swap config is untouched.

## Open Questions

- Which local models and quantizations to benchmark first (decided when writing the first serving profiles).
- Which exact judge model to pin for `judge-v1`, and how it is called. A GPT or Claude judge fits best, since neither family is benchmarked. It could run through the host's existing Codex or Claude Code login rather than an API key. Decided before task 8.2.
- Which non-llama.cpp backends will be used, and whether llama-swap can front them (beads `fitting-room-kap.1`).
- Whether Codex can use GLM at all: Codex requires the Responses API, and it is unverified whether z.ai offers one. If not, Codex runs only against local models served with a Responses-capable endpoint.
