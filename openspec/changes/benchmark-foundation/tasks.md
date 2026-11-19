# Tasks

## 1. Project scaffolding

- [x] 1.1 Create the `uv` project (`pyproject.toml`, `src/fitting_room/`, `fr` entry point) with Harbor pinned, and verify `uv run fr --help` and `uv run harbor --version` both work
- [x] 1.2 Create the directory layout from design D3 and a `.gitignore` covering `work/`, `results/` and `tasks/**/environment/repo/`, and verify `git status` shows no files from those paths after creating dummy files in them
- [x] 1.3 Install gitleaks and the OpenCode CLI on the host, and verify `gitleaks version` and `opencode --version` run
- [x] 1.4 Add a test setup (pytest) and lint (ruff) with one passing placeholder test, and verify `uv run pytest` and `uv run ruff check` pass

## 2. Harbor-on-Docker spikes (de-risk before building on it)

- [x] 2.1 Run Harbor's hello-world task with the built-in `oracle` and `nop` agents on Docker, and verify rewards 1.0 and 0.0
- [x] 2.2 Check GPU passthrough: a trivial task whose test runs `nvidia-smi` inside the container, pinned to one GPU, and verify it sees only that GPU. Record the result (and any `DockerEnvironment` subclass needed) in `docs/spikes.md`
- [x] 2.3 Check agent-phase network allowlisting: a task whose agent tries `github.com` and an allowed host, and verify the first is blocked and the second reachable. Record the result in `docs/spikes.md`
- [x] 2.4 Check that a sandbox reaches a host service on `host.docker.internal:18080` (a dummy HTTP server), and verify with a task test. Record the result in `docs/spikes.md`

## 3. Run configurations and campaigns

- [x] 3.1 Implement run-config and campaign TOML schemas with validation (missing harness version or effort, local model without serving profile, unknown arm or toolkit), and verify with unit tests for each rejection case in the benchmark-runs spec
- [x] 3.2 Implement `fr run <campaign>`: validate all configs, then invoke Harbor per config with repeats, writing results under `results/`, and verify on the hello-world task with 2 configs × 3 repeats that 6 trials are recorded
- [x] 3.3 Write the `fitting_room.json` sidecar (resolved config, serving profile, arm digest, task version) into each trial dir, and verify with a test that every trial from 3.2 has one
- [x] 3.4 Classify trials with Harbor `exception_info` as infrastructure errors, and verify with a test using an unreachable endpoint that the trial is excluded from pass rate
- [x] 3.5 Document config and campaign formats in `docs/running.md`, and verify the documented example campaign runs as written

## 4. Harness adapters

- [x] 4.1 Spike Hermes: find a headless one-shot invocation, a container install method, and where it writes usage. Record findings in `docs/spikes.md`, and verify a one-shot prompt completes non-interactively in a plain container
- [ ] 4.2 Add thin pinned subclasses for Harbor's `codex`, `claude-code` and `opencode` adapters with an empty harness home, and verify each passes a smoke task against a hosted model and that no host config is present in the container (test greps for host AGENTS.md, memories, hooks)
- [x] 4.3 Implement the Oh My Pi adapter from Harbor's `pi` adapter, with native log capture and ATIF conversion, and verify it passes the smoke task and produces an ATIF trajectory with tool calls
- [x] 4.4 Implement the Hermes adapter per the 4.1 findings, with native log capture, usage from `state.db`, and ATIF conversion, and verify it passes the smoke task with usage recorded
- [ ] 4.5 Implement arm mapping (design D6) for all five adapters with only `stock` populated, and verify a test arm with a marker sentence in `system_append.md` reaches each harness (the agent can echo it)
- [ ] 4.6 Implement toolkits (design D13): `toolkit.toml` schema, image-time install, runtime setup, optional announce text, per-harness MCP and skill registration, and refusal of unsupported items. Define `none` and `dev-stack` (bd, openspec, codebase-memory MCP with the repo indexed at build, the repo's skills), and verify that with `dev-stack` each of the five harnesses completes a smoke task calling `bd`, `openspec` and one codebase-memory tool, and that with `none` none of them are present
- [ ] 4.7 Document per-harness notes (versions, protocol support, toolkit support, known quirks) in `docs/harnesses.md`

## 5. Local model serving

- [x] 5.1 Implement `fr serve up|down <profile>` launching a standalone llama-swap config on port 18080 with explicit `CUDA_VISIBLE_DEVICES`, and verify the everyday llama-swap config file's checksum is unchanged after up/down
- [x] 5.2 Write the first serving profile for one local coding model on the 3090, and verify `/v1/models` lists it from inside a sandbox via `host.docker.internal:18080`
- [ ] 5.3 Implement the smoke gate (`fr serve smoke <profile> <harness>`: one-tool Harbor task run through the real harness), wire it into `fr run` so a failing pair is skipped with a reason, and verify with a deliberately broken profile (no `--jinja`) that it is skipped
- [ ] 5.4 Pass the smoke gate with Codex, Claude Code and OpenCode against the profile from 5.2, and record which protocol each used in `docs/harnesses.md`
- [ ] 5.5 Enforce the campaign GPU split (serving GPU versus task GPU, VRAM check against task `gpu_vram_gb`), and verify with a test campaign that a GPU task is not placed on the serving GPU

## 6. Session miner

- [x] 6.1 Define the candidate record and implement the Codex reader (subagent skip, commit from session metadata), and verify on fixture sessions with unit tests
- [x] 6.2 Implement the Claude Code reader with commit inference from branch and timestamp (marked inferred), and verify on fixtures including an unrecoverable-commit case
- [x] 6.3 Implement the Hermes reader (read-only SQLite, `parent_session_id` skip), and verify on a fixture DB and that the file is opened read-only
- [x] 6.4 Implement the Oh My Pi reader, and verify on fixture sessions
- [x] 6.5 Implement the repo filter, gitleaks redaction (regex fallback with warning) and `candidates.md`/`candidates.jsonl` output, and verify a fixture containing a fake API key comes out redacted with the count reported
- [x] 6.6 Run `fr mine` on the real history for the five priority repos, and verify that counts per source, repo and track are reported and that output stays under `work/` and out of git

## 7. Task authoring

- [x] 7.1 Vendor `evals-from-sessions` at `4e85a197` into `.agents/skills/evals-from-sessions/` with a `.claude/skills` symlink, LICENSE and `UPSTREAM.md`, and verify the files match upstream before local edits (diff recorded)
- [x] 7.2 Apply local skill changes (design D12: extra session sources, `fr mine` as candidate source, GPU metadata, investigative-checklist track, `fr task materialize`), and list them in `UPSTREAM.md`
- [ ] 7.3 Implement `fr task materialize` (`git archive` of the recorded repo and commit into `environment/repo/`), and verify the leak probe on a materialized task reports one commit and no remotes
- [ ] 7.4 Build per-repo base images for sd-scripts and pytortch-backend-experiments (CUDA) and data-processing and hcom (CPU), and verify each repo's test suite (or a documented subset) runs green in its image at a recent commit
- [x] 7.5 User checkpoint 1: review `candidates.md` and select about 20 candidates across the priority repos (record the selection in `work/mining/selected.md`)
- [ ] 7.6 Author and validate coding-track tasks from the selection (nop 0, oracle 5/5, mutants 0, alt-correct passes, leak probe clean, one smoke run), and verify each task's `report.md` shows all checks
- [ ] 7.7 Author and validate at least 3 investigative-track tasks (closed-set answers preferred), and verify the same way
- [ ] 7.8 User checkpoint 2: review finished tasks and reports. Accept 10–20 tasks into the benchmark at version 1.0.0

## 8. Scoring

- [ ] 8.1 Implement `fr score` computing the measured dimensions from ATIF and native logs (tokens, cost via `prices.toml`, time, turns, tool calls by tool, failed and repeated calls, verified-before-finishing, and per-item toolkit usage with its checks), and verify each with unit tests on fixture trajectories including unknown-usage, repeated-call, toolkit-provided-but-unused and shell-invoked `bd` cases
- [ ] 8.2 Implement `fr judge` with `judge-v1` (pinned cross-family model, yes/no criteria including "used available toolkit tools where they fit", final message stripped except for report honesty), and verify with a test that the judge input contains no final message and that a same-family pairing is refused
- [ ] 8.3 Implement `fr label` (terminal form over sampled trials) and agreement reporting (raw and κ, threshold 80% / 0.6), and verify on synthetic labels that a dimension below the threshold is reported as unvalidated
- [ ] 8.4 Implement `fr report`: per-config, per-dimension tables with spread across repeats, cost per passed task, infrastructure errors listed separately, grouping by task version and judge version, and verify on fixture results
- [ ] 8.5 Document score dimensions and how to read the report in `docs/scoring.md`

## 9. First campaign (integration)

- [ ] 9.1 Run a pilot campaign: accepted tasks × at least one config per harness (hosted) plus one local-model config, each with toolkit `none` and at least one harness also with `dev-stack`, 3 repeats, and verify the report renders with no unexplained infrastructure errors
- [ ] 9.2 User labels at least 30 pilot trials with `fr label`. Run calibration and record per-dimension agreement in `docs/scoring.md`
- [ ] 9.3 File beads issues for follow-up changes: OpenShell environment, multi-turn simulated user (Harbor multi-step / hcom), synthetic task generation (bug injection, answer-first Q&A, seeded flaws), persona/memory arms

## Workflow follow-up

- Archive the change after the pilot campaign report has been reviewed.
