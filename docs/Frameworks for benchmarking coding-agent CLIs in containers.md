# Frameworks for benchmarking coding-agent CLIs in containers

Nov 16, 2026 · @hoshino imi

## Bottom line

Harbor is the best fit for running Claude Code, Codex CLI, OpenCode and Gemini CLI headlessly in containers on custom tasks. Inspect AI with `inspect_swe` is the strongest alternative when you want to point those CLIs at local models. OpenHands' harness is the weakest fit for this job.

This was compiled from vendor docs read through a summarizer, so verify details like flag names against the docs before relying on them.

## Harbor (Terminal-Bench's harness)

Harbor has the widest adapter list, a simple file-based task format, a local Docker default and the best multi-step support.

- **Adapters:** claude-code, codex, opencode, gemini-cli, openhands, mini-swe-agent, aider, goose, swe-agent, copilot-cli, cursor-cli and many more. For the four main CLIs, all emit ATIF trajectories, support resume, and can act as the target in a simulated-user trial.
- **Task format:** a directory with `instruction.md`, `task.toml`, an `environment/` (usually a Dockerfile), `solution/solve.sh` and `tests/test.sh`. The verifier writes a numeric reward to `/logs/verifier/reward.txt`, or `reward.json` for multiple labeled rewards. A repo at a parent commit plus its test command maps onto this directly.
- **Sandboxes:** local runtimes are docker (default), podman, apple-container, singularity and sbx. Remote ones include daytona, e2b, modal, gke, ec2, runloop and many others. Support for compose, GPUs and network policy varies by provider.
- **Multi-turn:** multi-step tasks use a `steps/` directory with per-step tests. Each step starts a fresh conversation by default, `--resume-trajectory` continues the session, and the filesystem persists either way. A step's `min_reward` can stop the task early.
- **Logging:** ATIF output lands at `agent/trajectory.json`. Native session `.jsonl` files go under `agent/sessions/`. Phoenix can import ATIF as traces.
- **Caveat for local models:** per a 2026 paper, Harbor has no gateway that translates model-provider protocols, so putting a Qwen checkpoint behind Claude Code needs an Anthropic-compatible endpoint outside Harbor. Red Hat's `coding_agent_bench` wraps Harbor for self-hosted models and lists OpenCode, OpenHands, Pi and Qwen Code with vLLM as validated combinations.

## Inspect AI + inspect\_swe

Inspect's agents run inside the sandbox and proxy their model calls back to Inspect, which makes it the easiest route to local models.

- **Adapters:** Claude Code, Codex CLI, Gemini CLI, Kimi Code, OpenCode, Mini SWE Agent and Antigravity. Because model calls are proxied back to Inspect, any Inspect model works and token and time limits apply.
- **Task format:** Python code, not files. A `@task` combines a dataset (e.g. `json_dataset`), a solver such as `claude_code()`, a scorer and a sandbox. Each sample gets its own sandbox, and you can define a per-sample Dockerfile or compose file.
- **Sandboxes:** docker and local are built in. Extensions cover k8s, daytona, modal, openshell, ec2, proxmox and vagrant. Generated Compose configs default to no network.
- **Multi-turn:** not documented for the CLI agents. The Claude Code page offers only `attempts` for multiple scored tries and says nothing about resuming sessions. A separate package, `inspect-codex-app-server`, runs native Codex sessions in Docker sandboxes via the Codex App Server protocol.
- **Logging:** `.eval` is the default binary log format, with Inspect View, a log API and dataframes, and Inspect Scout for transcript analysis. It also has an MLflow integration.

## OpenHands benchmarks harness

OpenHands' harness is built around its own agent and a fixed set of suites, so custom CLI benchmarking takes the most extra work.

- **Adapters:** it mainly drives OpenHands itself. The SDK eval workflow has `--agent-type` values including `acp-claude` and `acp-codex`, but the benchmarks README doesn't mention other CLIs.
- **Task format:** fixed suites: SWE-Bench, SWE-Bench Pro, GAIA, Commit0, OpenAgentSafety and ProgramBench. The docs say the older generic harness-authoring guide is retired and there's no equivalent yet, so adding custom tasks means reading the source.
- **Sandboxes:** local Docker, or a remote runtime API that needs pre-built public images and a `RUNTIME_API_KEY`.
- **Multi-turn:** the agent loop is bounded by `--max-iterations`. Multi-step tasks aren't documented.
- **Logging:** results come out as `output.jsonl`, which a converter turns into SWE-bench prediction format. The README doesn't document the trajectory structure.

## Newer options

Three newer projects are worth a look, and one is best avoided.

- **[BenchFlow](https://pypi.org/project/benchflow/)** (Apache-2.0, 0.7.5 as of Aug 2026, so pre-1.0): drives any ACP agent, including Gemini CLI, Claude Code, Codex and OpenCode. Tasks are a `task.md` plus `environment/` and `verifier/` folders. Sandboxes are Docker, Daytona, Modal and AgentCore. It supports multi-agent and multi-round runs with a simulated user and writes rewards, token usage and full trajectories under `jobs/`. Its PyPI page contained text addressed to AI agents, asking them to upload local coding-session data to a prize program. I ignored it, and I'd be careful about pointing an agent at that page.
- **[EvalScope external agent bridge](https://evalscope.readthedocs.io/en/latest/user_guides/agent/bridge.html):** supports claude-code, codex, opencode, gemini-cli, hermes and deepseek-harness. It acts as a protocol translator between each CLI and your backend model, which suits local models well. CLIs run as a local subprocess or in Docker. Traces are replayable in a web UI, and coding tasks are scored from the working tree's `git diff`. Custom task format and multi-turn aren't documented on that page.
- **[Coder Eval](https://coder-eval.com/docs)** (UiPath): declarative YAML tasks with weighted scoring, Docker sandboxes, a simulated-user multi-turn mode, and JUnit output for CI. It targets testing your own CLIs and skills more than model comparison, and its license isn't stated.
- **Avoid:** [twaldin/harness](https://github.com/twaldin/harness), a unified wrapper for these CLIs, was archived on Oct 5, 2026.

## For your case

Start with Harbor, which has the widest adapter list, a simple task format, a local Docker default and the best multi-step support. Use Inspect with `inspect_swe`, or EvalScope, instead if you need to run CLIs against llama.cpp or vLLM without writing a protocol shim.

Whichever you choose, check that the CLI you care about can actually talk to your local endpoint before building tasks around it.

## Sources

- [Harbor pre-integrated agents](https://docs.harborframework.com/agents/pre-integrated-agents)
- [Harbor task overview](https://docs.harborframework.com/tasks/overview.md)
- [Harbor sandboxes](https://docs.harborframework.com/sandboxes/pre-integrated-sandboxes.md)
- [Harbor multi-step tasks](https://docs.harborframework.com/tasks/multi-step.md)
- [Harbor loading trajectories](https://docs.harborframework.com/core-concepts/jobs/loading-trajectories)
- [Polar paper (arXiv 2605.24220)](https://arxiv.org/pdf/2605.24220)
- [Red Hat coding\_agent\_bench](https://github.com/redhat-et/coding_agent_bench)
- [Inspect SWE](https://meridianlabs-ai.github.io/inspect_swe/)
- [Inspect SWE: Claude Code](https://meridianlabs-ai.github.io/inspect_swe/claude_code.html)
- [Inspect sandboxing](https://inspect.aisi.org.uk/sandboxing.html)
- [Inspect eval logs](https://inspect.aisi.org.uk/eval-logs.html)
- [inspect-codex-app-server](https://pypi.org/project/inspect-codex-app-server/)
- [OpenHands benchmarks](https://github.com/OpenHands/benchmarks)
- [OpenHands SWE-bench README](https://github.com/OpenHands/benchmarks/blob/main/benchmarks/swebench/README.md)
- [OpenHands evaluation harness docs](https://docs.openhands.dev/openhands/usage/developers/evaluation-harness)
- [BenchFlow](https://pypi.org/project/benchflow/)
- [EvalScope bridge](https://evalscope.readthedocs.io/en/latest/user_guides/agent/bridge.html)
- [Coder Eval](https://coder-eval.com/docs)
- [twaldin/harness](https://github.com/twaldin/harness)
