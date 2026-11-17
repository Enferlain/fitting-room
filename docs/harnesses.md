# Harnesses

Per-harness notes (task 4.7 will complete this). Harbor 0.26.0 ships built-in agents for all five harnesses in scope: `codex`, `claude-code`, `opencode` / `opencode-v2`, `hermes`, and `pi` (base for Oh My Pi). Check options with `uv run harbor agent schema <name>` and credential handling with `uv run harbor agent auth <name>`.

## Versions on the host

| Harness | Host version | Notes |
|---|---|---|
| OpenCode | 2.2.6 (nix profile) | npm's `opencode-ai` stable is 1.19.5; the 2.x line is what's installed. Use Harbor's `opencode-v2` agent. |
| Codex | `~/.local/bin/codex` | Local models only (user decision 2026-11-17: no GLM pairing for Codex). |
| Claude Code | 2.1.263 | GLM through `https://api.z.ai/api/anthropic` with a placeholder token (Agent Vault substitutes the real key). |
| Hermes | v0.0.0 (2026.9.24), upstream `27e38935` (nix); benchmark pin `f97608f1` (`v2026.9.24`) | Adapter `fitting_room.adapters.hermes:FrHermes`, a thin subclass of Harbor's `hermes` agent; see docs/spikes.md 4.1 for what it changes. |
| Oh My Pi | 18.12.6 (nix profile; npm `@oh-my-pi/pi-coding-agent`) | Adapter `fitting_room.adapters.omp:OhMyPi`, a thin subclass of Harbor's `pi` agent: installs Bun 1.3.14 + the npm package, runs `omp -p --mode json --approval-mode yolo`. Harbor's Pi trajectory/usage parsing works unchanged. Built-in `zai` provider reads `ZAI_API_KEY`. Day-to-day default `zai/glm-5.3:max`. |

## Local model smoke results

Serving profile `qwen35-9b-3080` (`uv run fr serve up qwen35-9b-3080`), task `spikes/hello`:

| Harness | Command | Protocol | Result |
|---|---|---|---|
| OpenCode 2.2.6 | `harbor run -p spikes/hello -a opencode-v2 -m openai/qwen3.5-9b --ak version=2.2.6 --ak base_url=http://host.docker.internal:18080/v1 --ae OPENAI_API_KEY=placeholder` | OpenAI-compatible via llama-server | reward 1, no exception, usage recorded (12,042 in / 6,030 cached / 65 out), ATIF `agent/trajectory.json` written (2026-11-17) |
| Hermes 2026.9.24 (`f97608f1`) | `fr run smoke-hermes` (`hermes-qwen35-9b`) | OpenAI-compatible via llama-server | reward 1, ATIF written, usage from the session export (10,644 in / 10,513 cached / 68 out) (2026-11-17) |

llama.cpp ignores the API key; the local placeholder is `no-key-required` because Hermes rejects obvious placeholders.

## GLM smoke results (via Agent Vault)

Benchmarks use GLM 5.3 / GLM 5.3 Flash and local models only (no GPT or Claude models). Sandboxes never hold a real key: Agent Vault on the host intercepts `api.z.ai` (containers resolve it to its FakeIP range through Docker Desktop's DNS forwarding) and substitutes the key in-flight. The container only needs Agent Vault's **public** root CA, mounted by a run-level overlay that sets `NODE_EXTRA_CA_CERTS`, `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` and `CURL_CA_BUNDLE`. Without it, TLS verification fails (`verify=20`).

| Harness | Command | Result |
|---|---|---|
| Oh My Pi 18.12.6 | `fr run smoke-omp` (`omp-glm53flash-medium`) | reward 1, no exception; ATIF trajectory with tool calls; omp reports z.ai-priced cost ($0.0013). For Flash it chose z.ai's OpenAI-compatible API (2026-11-17) |
| Claude Code 2.1.263 | `ANTHROPIC_AUTH_TOKEN=av-managed-key harbor run -p spikes/hello -a claude-code -m anthropic/glm-5.3-flash --ak version=2.1.263 --ak max_turns=10 --base-url https://api.z.ai/api/anthropic --api-key-name ANTHROPIC_AUTH_TOKEN --extra-docker-compose work/overlays/agent-vault-ca.compose.yaml` | reward 1, no exception (2026-11-17) |

**Cost caveat:** Claude Code reported `cost_usd: 0.171` for this run, which is its estimate at Anthropic prices, not GLM's. Scoring must compute GLM cost from `configs/prices.toml` and ignore harness-reported cost for non-native providers.

## Through `fr run`

`configs/campaigns/smoke-real.toml` (hello task, 1 repeat) passed for both supported pairs on 2026-11-17: `cc-glm53flash-medium` (Claude Code 2.1.263 + GLM 5.3 Flash) and `oc-qwen35-9b` (OpenCode 2.2.6 + local Qwen3.5-9B).
