# Questions for web instance

## 2, Does Harbor or Terminal-Bench support plugging in a custom sandbox/container backend, and how hard is it to add a new agent harness adapter?

Yes to both, and both are fairly easy, based on Harbor's docs. Terminal-Bench 2.0 doesn't need its own answer because its tasks use the Harbor task format and run on the Harbor harness. I didn't check the older standalone Terminal-Bench harness.

**Custom sandbox backend: supported, moderate effort**
- You subclass `BaseEnvironment` and implement a fixed set of methods. These are `type()`, `capabilities`, `_validate_definition()`, `start()`, `stop()`, `exec()` and four file upload/download methods. Harbor rejects classes that don't inherit from the base class.
- Declare only the capabilities your provider really enforces. If you claim `docker_compose`, you must also implement the per-service execution and file-transfer methods. A single-container backend avoids that.
- There's no plugin registry. You load it by import path, e.g. `harbor run ... -e my_sandbox:MySandbox`, or `import_path` in a config file. The module and your provider SDK must be installed in the same Python environment as Harbor, and `harbor environment list` won't show it.
- Options can go through `--ek key=value`, validated against an `EnvironmentOptions` subclass if you define one, and an optional `preflight` classmethod can check credentials before trials are queued.
- **No-code alternative:** there's a draft convention called ASP (Agent Sandbox Protocol). A harness reads an `.asp.json` file with host, port and user, then routes its tool I/O over SSH, so the sandbox just needs an SSH endpoint with command execution, SFTP and key or token auth. It's an RFC, not a finished feature, and the docs frame it as a harness-side mechanism, so I wouldn't assume it replaces a Harbor environment class.

**New agent adapter: small to start, more work to do it properly**
- Use `BaseInstalledAgent` for most CLIs, where Harbor installs and runs the agent inside the task environment. Use `BaseAgent` only when the agent loop runs outside the container and acts through `environment.exec`.
- An installed agent needs `name()`, `install()` and `run()`. `configure()` (credentials, MCP registration) and `populate_context_post_run()` (usage and trajectory parsing) are optional. The docs' abridged example is about 15 to 25 lines, and the docs give no size estimate. Registration is by import path again: `harbor run -t <task> -a your_module.path:MyAgent`.
- A minimal adapter that just runs the CLI with the instruction and gets scored by the tests is an afternoon's work. The extra effort is in:
  - credential and endpoint wiring, via a `MODEL_CONNECTION` spec and `self.model_connection`;
  - converting the CLI's session logs to ATIF (the page doesn't document this, so you'd copy the Claude Code or Terminus-2 adapters);
  - resume support, if you want multi-step tasks to continue a session.
- If your adapter honors `--base-url`, declare `AgentCapabilities(base_url=True)`. That matters for pointing a CLI at a local endpoint.

**Not an extension point:** Harbor's plugins only react to job and trial events (start, end, verification). The docs describe them as hooks that run outside the sandbox, not a way to add agents or environments.

Next I'd read the source of an existing adapter close to what you need before writing your own.

Sources:
- [Harbor custom sandboxes](https://docs.harborframework.com/sandboxes/custom-sandboxes.md)
- [Harbor ASP](https://docs.harborframework.com/sandboxes/asp.md)
- [Harbor custom agents](https://docs.harborframework.com/agents/custom-agents.md)
- [Harbor plugins](https://docs.harborframework.com/plugins/custom-plugins.md)
- [Terminal-Bench paper (ICLR 2026)](https://proceedings.iclr.cc/paper_files/paper/2026/file/444a3737adaee10d86ad2ef5f74468e6-Paper-Conference.pdf)

## 3, Is there any tool that converts real coding-agent session transcripts (Claude Code / Codex JSONL logs) into reproducible benchmark tasks? Look for projects or papers on mining personal or organizational agent logs into evals.

Yes. There is one tool that does this end to end, plus several papers describing the same pipeline. I read the plugin's directory listing and the papers, not the plugin's source repository.

**The tool: `evals-from-sessions`**
- It's an MIT-licensed agent skill that turns your own coding-agent sessions into verified Harbor eval tasks, so you can compare agents, models and settings on your own work by cost and time. The listing names Claude Code, Codex, Pi, Gemini CLI and other JSONL session exports. The source is at `github.com/ibragim-bad/evals-from-sessions`.
- The workflow has six steps. It copies your session files, scans the copy with gitleaks, and lists candidate task episodes. It then builds the Harbor task from either a snapshot of your repo (private mode) or a re-authored synthetic task (shareable mode), and tries to block cheating paths such as future git history and visible tests.
- The verification step is careful. A nop solution must fail, an oracle solution must pass 5 of 5 runs, near-miss solutions must fail, and an alternative correct solution must pass. You approve the candidate list, then the task spec, then each finished task.
- It needs Docker, git, Python 3.11+, Harbor, gitleaks 8 and credentials for one agent. Private-mode tasks contain a snapshot of your repository, so they should stay private.
- It's a community project, and the directory page gives it a 45/100 "Promising" confidence score and says that is not a security audit. Read the skill's code before pointing it at your session history, since transcripts can hold keys and private code.

**Papers that do the same conversion**
- **ProdCodeBench / REAP** (arXiv 2604.01527; the PDF and HTML versions carry different titles):
  - Verbatim developer-agent conversations are mapped to the diffs that landed, and the solution diff is reverted so the agent can't read the answer.
  - Candidate tests are retrieved and prompts are filtered for quality and testability.
  - Tests run three times with two warmups, and a test counts as fail-to-pass only if the third run fails.
  - It yielded 132 fail-to-pass tasks. The corpus is proprietary. The paper links artifacts such as classifier prompts and annotation protocols, but doesn't confirm that the full pipeline code is public.
- **SWE-Together** (arXiv 2606.29957): builds multi-turn tasks from recorded sessions.
  - About 11,260 raw sessions yielded 109 tasks, around 1%.
  - It filters deterministically, screens with an LLM, then a sandboxed agent writes the task package.
  - An LLM user simulator replays the original user's intent, choosing after each turn to stay silent, ask a question, redirect or add a requirement.
  - Reference patches score only about 78%, so the rubric isn't a strict ceiling. The paper links a repository at `github.com/Togetherbench/SWE-Together`, which I couldn't verify.
- **RealClawBench** (arXiv 2606.03889): 76,155 tool-use sessions were narrowed to 281 released tasks. It rebuilds the workspace from session evidence, rewrites the request as a standalone instruction, and attaches a deterministic verifier. Raw logs, credentials and proprietary files are excluded from release. The source logs come from OpenClaw, not Claude Code or Codex.
- **SWE-TaskFlow** (JetBrains, arXiv 2610.09633): an opinion paper that studies 4,782 real agent sessions and argues benchmarks should match real task flows. It's useful for what to measure, not a converter.

**What all of these say about the work involved**
- Yield is low, roughly 1% of sessions in SWE-Together. You need many sessions, or you end up hand-curating.
- You need the repo state recoverable at the session's start, which in practice means a pinned commit. Sessions without one are dropped.
- Tasks that depend on external state (deploys, PRs, credentials) or subjective judgment get rejected.
- The strict part is the verifier. REAP and `evals-from-sessions` both insist on a fail-before, pass-after check, with repeated runs to catch flaky tests.

**Not task converters:** `claude-code-transcripts`, `codex-replay` and similar tools only render the JSONL files as HTML for reading. A blog post also sketches a hand-rolled Codex session-to-eval flow, but it's a recipe, not a tool.

For your plan, `evals-from-sessions` is the closest match, because its output is Harbor tasks and you're already considering Harbor. Run it on a few of your own sessions first and see how many survive its verifier checks.

Sources:
- [evals-from-sessions listing](https://www.claudepluginhub.com/plugins/ibragim-bad-evals-from-sessions)
- [ProdCodeBench / REAP (arXiv 2604.01527)](https://arxiv.org/pdf/2604.01527)
- [SWE-Together (arXiv 2606.29957)](https://arxiv.org/html/2606.29957)
- [RealClawBench (arXiv 2606.03889)](https://arxiv.org/html/2606.03889)
- [SWE-TaskFlow (arXiv 2610.09633)](https://arxiv.org/html/2610.09633v2)
- [claude-code-transcripts](https://github.com/simonw/claude-code-transcripts)
- [Codex session transcript tooling overview](https://codex.danielvaughan.com/2026/05/21/codex-cli-session-transcripts-jsonl-replay-viewer-tools-audit-analysis/)

## 4, What methods exist for automatically generating repo-specific coding benchmark tasks from a codebase or its git history? E.g. SWE-smith, SWE-Gym, SWE-rebench, R2E, nemo-style synthetic task generation. How do they verify the generated tasks are solvable and well-specified?

There are three families of methods. They differ mainly in how much they verify. Execution-based checks (does the task fail before the fix and pass after) are standard everywhere, while checks on whether the task is well specified are weaker and often LLM-only. I read the papers through a summarizer, and several of the cited details come from sections I could only partly see.

## Mining real history
- **SWE-Gym:** the manual-effort baseline. 358 repositories were reviewed and 64,689 candidate instances extracted. Human effort in validation and environment setup produced 2,438 validated instances.
- **SWE-rebench V2:** an automated version of the same idea, across languages.
  - An interactive setup agent installs the repo and refines scripts from errors. Setup is inferred once per repository and reused for all of its tasks.
  - It extracts tests by running the suite twice. It applies the test patch and runs the suite, then applies the solution patch and runs it again, and keeps only instances with at least one fail-to-pass test.
  - The funnel is steep: 29.5M raw PRs end up as 32,079 tasks after issue-text filtering, and only about 20% of repositories succeed with a single setup attempt.
- **SWE-Factory:** automated fail2pass validation on 1,030 raw instances reached 92% precision and 100% recall against manual annotation. It builds environments with a multi-agent system, and its environment check is that tests pass after the patch is applied.
- **SWE-Universe:** the agent repeatedly tests the generated verifier against both the buggy and fixed repository states, diagnoses failures and revises the build procedure.
- **R2E-Gym (SWE-GEN):** works from commits, so it doesn't need human-written issues or tests.
  - Existing tests identify fail-to-pass tests, and commits without tests get automatically generated ones.
  - An LLM then writes the problem statement from the code change, with the fail-to-pass tests in the prompt, because test execution information gave more precise statements than code alone.
  - It's a fork of the same idea, adding statement back-translation, rather than a separate paradigm.

## Synthesizing tasks on a real repo
- **SWE-smith** uses five bug-generation strategies:
  - **LM Modify.** An LM introduces errant changes to a function or class. Yield was 56%.
  - **LM Rewrite.** An LM rewrites a function from its signature and docstring. Yield was 35%.
  - **Procedural Modification.** Random AST transformations. Yield was 40.2%.
  - **Combine Bugs.** Merges candidates into multi-location tasks. Yield was 96.9%.
  - **PR Mirror.** An LM undoes a PR's changes on the current repo version. Yield was 33.8%.
  - Validation is purely behavioral: each candidate is applied, the suite is run, and only patches that break one or more previously passing tests are kept. Runs over two minutes are discarded.
- **SWE-Hub's Bug Agent:** extends this to system-level regressions across modules, paired with user-like issue reports.
- **SWE-Future:** writes the issue, test patch and gold patch itself, then admits the task only after leakage review, FAIL_TO_PASS validation and selected preservation checks.

## From-scratch synthesis (NeMo style)
I read "nemo-style" as NVIDIA's NeMo Data Designer pipeline in the Nemotron 3 Super report.
- Seed tasks come from a taxonomy of 24 actions users take in agentic CLI tools, and Data Designer generated about 20k queries from it.
- An LLM judge removed tasks that reference an existing codebase, leaving about 15k, each paired with a markdown spec.
- The report doesn't describe a solvability check. Teacher agents generated traces that were "filtered, normalized", with the criteria unspecified. This family relies on LLM judging and trace filtering rather than execution, so it's the weakest on solvability.

## How they check solvability and specification

**Solvable (does a correct solution exist and pass?):**
- A fail-to-pass test must fail before and pass after the reference change. All the history-mined pipelines do this, and SWE-smith's version is that a candidate must break at least one passing test.
- Flaky tests are mostly not handled in these papers. The REAP paper from the earlier session-mining answer is the exception, running tests multiple times with warmups.
- Some check the environment itself: SWE-Factory's and SWE-Universe's loops rebuild until tests run.

**Well specified (can the problem be solved from the statement alone?):**
- SWE-rebench V2 is the most explicit. Three LLM judges score each issue on an adapted SWE-bench Verified rubric, and an instance is kept only if all three rate the specification adequate. Calibrated against human labels, the chosen configuration had precision 0.83 but recall 0.10. In other words, it rarely lets a bad task through but discards most good ones.
- SWE-smith has no systematic statement check. Its ablations found that including the fail-to-pass test text in the prompt leaked the evaluation criteria and hurt performance.
- R2E-Gym's main leakage control is removing repositories that overlap with the SWE-Bench test set.

## Known failure modes
- **Tests expecting names the statement never gives.** SWE-rebench V2 lists this among its limitations.
- **Toxic generated tests.** R2E-Gym reports up to 10% of generated tests being "toxic" in some problems.
- **Difficulty isn't the same as value.** In SWE-smith, harder subsets did not clearly make better training data.
- **Single-container environments only,** in SWE-rebench V2, which excludes multi-service systems.

## What this means for your repos
You want benchmark tasks, not training data, so I'd borrow the strict checks from `evals-from-sessions` (a nop solution must fail, an oracle must pass several times) and combine them with a SWE-smith-style injection for volume. A cheap unanimous-judge spec check (as in SWE-rebench V2), plus hand review of a sample, would cover the part the papers handle weakly. I'd treat any task that passes these automated checks as probable, not proven.

Sources:
- [SWE-smith](https://arxiv.org/html/2504.21798v2)
- [SWE-Gym (ICML 2025)](https://proceedings.mlr.press/v267/pan25g.html)
- [SWE-Gym review](https://www.themoonlight.io/en/review/training-software-engineering-agents-and-verifiers-with-swe-gym)
- [SWE-rebench V2](https://arxiv.org/html/2602.23866v1)
- [R2E-Gym](https://arxiv.org/html/2504.07164v1)
- [SWE-Factory](https://arxiv.org/html/2506.10954v1)
- [SWE-Universe](https://arxiv.org/html/2602.02361v2)
- [SWE-Hub](https://arxiv.org/html/2603.00575v1)
- [SWE-Future](https://arxiv.org/html/2606.18733)
- [Nemotron 3 Super technical report](https://research.nvidia.com/labs/nemotron/files/NVIDIA-Nemotron-3-Super-Technical-Report.pdf)

## 5, How do benchmarks evaluate non-coding repo work like codebase Q&A, exploration, architecture explanation, or design discussion? Any benchmarks or rubric approaches for 'agent understanding of a codebase'?

I found no execution oracle for this kind of work, so the benchmarks use three substitutes: rubrics or checklists graded by an LLM judge, comparison against reference answers, and ground-truth code regions for exploration. The papers are all recent (2026) and I read them through a summarizer, so treat exact numbers as approximate.

## Codebase Q&A

**Expert-written (highest quality, small):**
- **SWE Atlas, Codebase Q&A** (Scale): professional engineers wrote 124 tasks from 18 actively maintained GPL repositories, each a single under-specified question with an expert reference solution.
  - Sub-categories include architecture and system design, root-cause analysis, code onboarding, security, and API usage. Answering often requires setting up the app and running live requests.
  - Grading is rubric-only with an LLM judge, averaging 10.5 rubrics per task. A task passes only if every rubric item passes.
  - It runs on Harbor, so it fits your earlier setup. Runs use Harbor on Modal sandboxes, with vendor scaffolds (Codex CLI, Claude Code, Gemini CLI) or mini-SWE-agent.
- **RubberDuckBench:** a tiny benchmark with questions derived from PR review comments, and rubrics written manually by three authors, taking about 12 person-hours each. An LLM judge was tested and rejected because its reliability was lower than humans' (ICC3 = 0.709 vs .991). Hallucination appeared in 58.3% of responses on average.

**Mined from real discussions:**
- **SWE-QA:** 720 question-answer pairs from 15 Python repositories, built from crawled GitHub issues, with human evaluation agreeing closely with the LLM judge. Its taxonomy is What/Why/Where/How.
- **CoReQA, CodeRepoQA, StackRepoQA:** build repository question sets from issue threads, maintainer dialogues, and community answers.
- **RepoProbe:** uses answered GitHub Discussions because they tend to ask "how" and "why" questions without pointing to specific files. It keeps 500 validated pairs across 50 repositories, in the categories Project Architecture, Business Logic and Implementation Details.

**Auto-generated with controls:**
- **Code-QA-Bench:** generates answers first. An agent explores the source with read-only tools and writes a gold answer before any question is written, then a question and rubric are derived from it. To separate reasoning from memorized docs, each task runs closed-book, code-only (docstrings, comments and docs stripped) and fully documented. Its limitations: one judge, no human validation, and Python only.

## Exploration and navigation
- **SWE-Explore** scores exploration directly. The agent returns a ranked list of up to 5 code regions under a line budget, across 848 issues and 203 repositories. Ground truth comes from the lines read in at least two successful solution trajectories, with regions read in every trajectory forming the core context. Metrics include line-level precision, recall and F1, plus nDCG under the budget and context efficiency. As a sanity check, hiding everything outside an explorer's regions from a fixed patcher showed context efficiency correlating strongly with resolve rate (r = 0.95). A caveat: it covers only instances that at least one agent solved, and trajectory-derived truth may miss other valid evidence.

## Design, architecture and judgment
- **Senior SWE-Bench** (Snorkel, Harbor-compatible) grades open-ended design with a stack: expert-written behavioral tests, a validation agent that writes tests adapted to each solution from a hidden spec, a task-specific rubric judge, and a "taste judge" on global quality rubrics. Each task runs with oracle and no-op patches, and is rejected if the validation agent is inconsistent on either.
- **Architecture Quality Judge:** generates a repository- and issue-specific architectural rubric from source evidence before scoring a patch against it. It judges code changes, not Q&A, but the rubric-from-source idea transfers.
- **CodeWikiBench:** grades generated documentation with a rubric that mirrors the project's architectural structure with weighted requirements, assessed by judge agents.
- **CAKE:** 188 expert-validated questions on cloud-native architecture across four cognitive levels. It tests general architecture knowledge, not understanding of a specific repo.

## Rubric techniques that recur
- **Weighted checklists beat holistic scores.** In RepoProbe, each answer is scored out of 10: one to four knowledge items share 9 points, and a clarity criterion is worth 1. Over five runs, the checklist had about 1.5–2.4% standard deviation versus about 2.9–3.5% for a 5-dimension Likert judge.
- **Negative rubrics.** RubberDuckBench starts at full points and deducts, penalizing hallucinated information more heavily than omissions. SWE Atlas also includes negative rubrics.
- **A judge from a different model family.** Code-QA-Bench deliberately picked a judge from a different provider than the task generator.
- **Validate rubrics.** SWE Atlas removes rubrics flagged as invalid, over-prescriptive or ambiguous by at least 2 of 3 expert auditors, and reports judge agreement (κ 0.74–0.84). It also recommends pinning the judge version.

## What the results show
- **Fluent but incomplete.** In RepoProbe, clarity scores were consistently higher than knowledge scores, so fluent answers often missed required facts, and no model exceeded the low 60s.
- **Edit bias.** Models proposed code or configuration changes before understanding the architecture, accounting for 10.4% to 24.0% of low-scoring failures depending on the model. Worth measuring if your agents tend to jump into edits.
- **Different failure styles.** In SWE Atlas, GPT models often left rubric sub-questions incomplete, while Claude models often lacked runtime evidence and explained code instead.

## For your repos
The most reusable recipe is Code-QA-Bench's answer-first generation combined with RepoProbe's weighted checklists. Have an agent explore your repo and write a verified answer, derive the question and a 3 to 5 item checklist from it, then grade with a pinned judge from another model family. For the benchmark's honesty, hand-check a sample of checklists and run the stripped-docs condition on a few questions. If you want exploration measured separately, copy SWE-Explore: record the lines a strong agent read while solving a task you already have tests for, and score other agents against that.

Sources:
- [SWE Atlas](https://arxiv.org/html/2605.08366v1)
- [SWE-QA](https://arxiv.org/pdf/2509.14635)
- [CoReQA](https://arxiv.org/html/2501.03447)
- [Deep Agentic Search for Repository-Level Code QA](https://arxiv.org/pdf/2608.01507)
- [RepoProbe](https://arxiv.org/html/2608.04783)
- [Code-QA-Bench](https://arxiv.org/pdf/2605.29277)
- [SWE-Explore](https://arxiv.org/html/2606.07297)
- [RubberDuckBench](https://arxiv.org/html/2601.16456v1)
- [Senior SWE-Bench](https://senior-swe-bench.snorkel.ai/blog/2026-06-16-how-it-works)
- [Architecture judges](https://arxiv.org/html/2606.14948v2)
- [CodeWiki / CodeWikiBench](https://arxiv.org/html/2510.24428v1)
- [CAKE](https://www.alphaxiv.org/abs/2604.05755v1)

## 6, What are best practices for simulated users in agent benchmarks (tau-bench, tau2-bench, and later work)? How do they keep the simulated user consistent, prevent it from leaking the answer, and measure how much simulator noise affects scores?

The practices are clearer on consistency and leak prevention than on measuring noise. Here is what I found, read through a summarizer. Some of the tau2 "recommendations" below are inferences from the paper, not an explicit list.

## Keeping the simulator consistent
- **Give it a private, structured scenario.** In τ-bench the simulator's system prompt is the user's instruction (a persona and goal, e.g. change a reservation, cancel and rebook if that's not possible). Evaluation compares database state at the end of the episode, so the user doesn't need to be scripted turn by turn. In τ²-bench, each task gives the simulator a reason for the call, known and unknown information, and task-specific behavioral instructions, and personas (None, Easy, Hard) can also be assigned.
- **Constrain it through the environment, not just the prompt.** The τ²-bench paper's main reliability claim is a user simulator tightly coupled with the environment, whose behavior is constrained by tools and observable states. Its tools act on a mocked phone database, return human-readable outputs only, and responses are tied to the underlying device state.
- **One action per turn.** The simulator prompt requires one message or one tool call per turn, progressive disclosure of details, and tool calls only when the agent requests them.
- **Keep the user dependent on the agent.** The paper's apparent design principle is "complexity asymmetry", so the user still needs the agent's help.
- **Review traces iteratively.** Sierra's own approach was to fix implementation errors and task specification errors first, then evaluate the simulator's quality. The paper separates the three sources of uncertainty (implementation, task specification, simulator).

## Preventing leakage and invention
- **Prompt rules.** τ²-bench's simulator prompt says it must not invent information beyond its scenario and must not fabricate tool results.
- **Measure violations directly.** UserProxyBench (Sept 2026) scores the user separately from the agent. Each task gets 4–8 atomic criteria generated from the private user blueprint, the simulator guidelines and the user tool surface, and an episode scores 1 only if the user passes every applicable one. The criteria fall into four families: groundedness, premature disclosure, goal deviation, and missed information.
- **What leakage costs.** Premature disclosure was the most common failure, yet it barely changed agent pass rate (about −.04), though over-disclosing users led the agent to make fewer tool calls. A violation can leave the reward unchanged while the agent is no longer solving the intended interaction. Also note that 24.4% of agent-successful episodes contained a user-criteria violation.
- **Coding analogue:** SWE-Together's simulator (from the earlier session-mining answer) makes one structured choice after each agent turn: no-op (the default), question, redirect, new requirement, or check external, conditioned on analysis of the original user's goals. Defaulting to silence is itself a leak-prevention measure.

## Measuring simulator quality and noise
- **Human audit.** In τ²-bench, two annotators scored each user turn on four criteria (guideline adherence, instruction adherence, correct tool use, natural continuity), labeling errors critical or benign. Critical error rates were 13% in airline, 12% in retail and 6% in telecom (the paper's table caption and text disagree on the telecom figure, so check it).
- **Run-to-run noise floor.** A GitHub analysis of τ²-bench's published results, found that two single retail runs must differ by about 7–9 points to be distinguishable from repetition noise, and 33–55% of retail tasks flip verdict across identical runs. Airline needs 5.5–11 points. These figures include simulator sampling, so they're a floor for the benchmark as published, not for the agent alone. It also suggests reporting a floor per agent and domain, not one board-wide number, and adding an interval on pass^1.
- **Separating the sources.** In that analysis, a re-grade found that the judge contributed little (1 flip in 256 gradings). The rest is agent plus user simulator, and agent variance depends on the model.
- **Varying the simulator.** Swapping the user proxy with the agent fixed moved mean reward from .644 to .796 in UserProxyBench. Lost in Simulation (ACL 2026) found that agent success rates vary up to 9 percentage points across different user LLMs.
- **Variance decomposition tooling.** The `whose-noise` project splits τ-bench variance into simulator, agent and task with ANOVA and a task-cluster bootstrap. It has no results yet, so treat it as a method, not evidence.
- **Pass^k itself** was designed for repeat consistency, but if the simulator is stochastic, variance across k trials mixes agent and simulator inconsistency.

## Known biases
- **Benevolence.** One 2026 paper notes standard LLM simulators tend to be overly cooperative. A June 2026 study measured "decision fidelity" against real purchase outcomes: simulated customers disengaged less than real ones, and telling the simulator it may disengage cut the marginal bias fivefold but barely moved the outcome-conditioned gap.
- **Miscalibration.** Compared with real people, simulated users underestimated success on the hardest tasks and overestimated it on moderately difficult ones, and differed in artifacts like extra politeness and question-asking. Performance as a proxy also varied by dialect.
- **Default simulator glitches.** The LongCat report says τ²-bench's default simulator occasionally behaves abnormally, adding noise, and that airline annotation issues cause spurious failures.

## For a coding-agent simulated user
Tie the simulator to state it can observe, give it a rubric-checkable blueprint, and default to silence. Run at least two different simulator models and several repeats, and report the spread. Score the user's behavior separately from the agent's, as UserProxyBench does. Keep a small human-audit sample, since automated fidelity checks have a blind spot where the generator and judge are the same model.

Sources:
- [τ-bench](https://proceedings.iclr.cc/paper_files/paper/2025/file/1b126cc38b8638e07bef37e7b2bb72bf-Paper-Conference.pdf)
- [τ²-bench](https://arxiv.org/pdf/2506.07982)
- [τ²-bench noise floor (issue #540)](https://github.com/sierra-research/tau2-bench/issues/540)
- [UserProxyBench](https://arxiv.org/html/2609.38043v1)
- [Lost in Simulation](https://aclanthology.org/2026.acl-long.2192/)
- [whose-noise](https://github.com/nilay007hckkr/whose-noise)
- [Decision fidelity](https://arxiv.org/html/2606.20708)
- [Diversity-guided user simulation](https://arxiv.org/pdf/2604.21480)
- [LongCat-Flash-Thinking-2601 report](https://arxiv.org/pdf/2601.16725)
- [SWE-Together](https://arxiv.org/html/2606.29957)

## 7, How do current agent benchmarks score beyond pass/fail: efficiency, cost, tool-use quality, trajectory/process quality, problem-solving approach? Are there published rubrics or trajectory-grading methods (LLM-as-judge on trajectories) and evidence on how well they agree with human judgment?

Searching for process-level scoring methods and evidence on how well trajectory judges agree with humans.

Outcome-only scoring is widely seen as insufficient, and there's now a layer of process metrics and trajectory judges on top of it. The evidence on judge-human agreement is the weakest part: most agreement numbers come from papers validating their own judge on a small sample. Some sources below are aggregator or blog summaries, flagged where it matters.

## What gets scored beyond pass/fail

- **Cost and efficiency.** The "AI Agents That Matter" paper argues that all agent evaluation must control for cost, reporting accuracy against dollars on a Pareto frontier. Cost metrics in the literature group into token and monetary cost, time cost, resource cost, and interaction cost, and TPS-Bench proposes cost-of-pass to connect monetary cost with completion rate. A hardware-aware variant, PTE (Prefill Token Equivalents), exists because token and tool-call counts don't capture real inference latency. It also counts non-reusable context cost, which matters for local models.
- **Tool-use quality.** The common decomposition is tool-call precision (correct calls over calls issued) and argument accuracy (separating "wrong API" from "right API, filled wrong"). MLflow ships a ToolCallEfficiency judge that flags redundant calls with the same or similar arguments.
- **Process defects.** ProcCtrlBench defines 11 defect types in four categories: context management, tool-use efficiency, workflow architecture, and tool-ecosystem consistency. A secondary summary of its results says process quality depends jointly on model capability and agent orchestration, since the same model behaves differently across agent frameworks. CodeTraceBench provides code-agent trajectories with step-level annotations and failure-critical labels.
- **Problem-solving approach, "lucky passes".** AgentLens is the most direct attempt. It's reference-based, not an LLM judge: it merges multiple passing trajectories into a Prefix Tree Acceptor of known-good strategies and scores candidates against it. Its "Lucky Pass" label covers passes reached through regression cycles, blind retries, missing verification, or disordered work (10.7% of passes in its subset). Quality-score rankings differed from pass-rate rankings for all eight models, and Lucky rates ranged from 0.5% to 23.2%. Its quality score was only validated against pass/fail outcomes, with no human or LLM-judge agreement numbers found for process quality itself.

## Trajectory-grading methods

- **Rubric LLM judges.** Typically 3–5 dimensions scored 1–5, or atomic binary criteria checked against the trace.
- **Agent-as-a-Judge.** The judge is itself an agent with tools, which can verify intermediate steps by locating code and executing files, not just reading text. It was tested on DevAI, 55 tasks with 365 hierarchical requirements.
- **Step-level error localization.** TRAIL has judges find the specific failing step and classify it, rather than marking the whole task failed.
- **Deterministic or reference-based checks** (AgentLens, tool-call counters) don't depend on a judge.

## How well judges agree with humans

- **Agent-as-a-Judge (DevAI):** 92.07% (gray-box) and 90.44% (black-box) alignment with human consensus, versus 70.76% and 60.38% for plain LLM-as-a-judge. This is the authors' own benchmark, scored against three human experts on one agent.
- **Web agents (AgentRewardBench, 1,302 trajectories, 12 judges):** the most independent test. No judge exceeded 70% precision on success, so roughly 30% of "successes" weren't. Inter-annotator agreement was 89.3%. Side-effect detection was poor (about 14% precision for the best judges); repetition detection was much better (80–90%). Judges also tend to accept the agent's own reasoning even when it's wrong.
- **Rule-based checkers can be the worse proxy.** On the same benchmark, rule-based scoring had 83.8% precision but only 55.9% recall.
- **Rubric scoring, other domains:** a travel-planning benchmark found LLM-vs-human error (MAE 0.52) close to human-vs-human (0.48). A phone-agent benchmark found 89% agreement on task success (κ = 0.77) for a full-trajectory judge, but κ of 0.51–0.61 for a per-step judge that was more lenient. Several other 2026 papers report 88–92% agreement for their own judges.
- **Debugging traces is harder than grading them.** On TRAIL, the best model scored 11% joint accuracy, though that's with 2025-era models.

## Known judge failure modes

- Trajectory-length bias, hallucination blindness (missing a call to an undefined tool), and argument blindness (missing wrong argument values).
- Self-preference and verbosity bias, which show up when a judge rates its own model family higher or favors longer answers.
- Instability: one 2026 audit of SE judges notes there's no standard quantification of test-retest consistency. Its practical advice is to trigger verification, such as compilation, static analysis or tests, when a judge can't be trusted.
- Mitigations from the practitioner literature: run pairwise comparisons in both orders and keep only verdicts that agree, and use a judge from a different family than the agent.

## For your setup (my suggestions, not from the papers)

1. Keep tests as ground truth, and add deterministic log metrics: tokens, dollars or tokens/s, wall time, tool-call count, repeated identical calls, failed test runs, and whether tests were run before finishing.
2. Report cost against pass rate across repeated runs, not a single score.
3. Add a binary-criteria LLM judge only for what logs can't capture (scope creep, approach, explanation quality), using a different model family.
4. Hand-label 30–50 trajectories first and report judge agreement (raw and κ) for your own tasks, since published agreement doesn't transfer.

Sources:
- [AI Agents That Matter](https://arxiv.org/pdf/2407.01502)
- [Toward Efficient Agents](https://arxiv.org/pdf/2601.14192)
- [PTE hardware-aware TIR efficiency](https://arxiv.org/pdf/2604.05404v1)
- [NVIDIA: evaluating agents from tool calls to task completion](https://developer.nvidia.com/blog/how-to-evaluate-ai-agents-from-tool-calls-to-task-completion/)
- [MLflow ToolCallEfficiency](https://mlflow.org/docs/latest/genai/eval-monitor/scorers/llm-judge/tool-call/efficiency/)
- [ProcCtrlBench](https://arxiv.org/html/2605.20251v2) (results via [benchmarklist summary](https://benchmarklist.com/benchmarks/procctrlbench_evaluating_process_level_defects_and_control_preservation_in_llm_coding_agents/))
- [AgentLens](https://arxiv.org/html/2605.12925)
- [CodeTraceBench](https://www.alphaxiv.org/abs/2604.11641.md)
- [Agent-as-a-Judge / DevAI](https://arxiv.org/pdf/2410.10934) (numbers via [FutureAGI summary](https://futureagi.com/blog/agent-as-a-judge/))
- [AgentRewardBench](https://arxiv.org/html/2504.08942v2)
- [TRAIL](https://arxiv.org/html/2505.08638v2)
- [iOSWorld](https://arxiv.org/pdf/2606.09764)
- [Beyond Itinerary Planning](https://arxiv.org/pdf/2512.22673)
- [BabelJudge](https://arxiv.org/pdf/2606.22329)
- [Bias in the Loop](https://arxiv.org/html/2604.16790)
- [LLM-as-Judge for Agents](https://agentic-ai-wiki.vercel.app/operations/evaluation-and-observability/llm-as-judge-for-agents/)

## 8, What are known failure modes of LLM-as-judge for grading coding agent trajectories (self-preference bias, length bias, position bias), and recommended mitigations like reference answers, checklists, pairwise comparison, judge ensembles?

Most of the evidence on trajectory judges comes from synthetic or non-coding testbeds, and the coding-specific evidence is thin and mostly from preprints. The classic biases do exist, but the newest results suggest a bigger problem for coding agents: judges get fooled by how a trajectory reads.

## Failure modes

**Self-preference.** Judges favor their own outputs, and the cause is debated. One analysis found LLMs give higher scores to lower-perplexity (more familiar) text than humans do, whether or not the model wrote it. Others tie it to self-recognition, and a 2026 paper attributes almost 90% of observed self-preference to evaluator uncertainty. In the rubric-based study, self-preference grew with output length on LiveCodeBench. In coding audits it's a live concern: DeepSWE's judge was GPT-5.5, which was also the top-ranked configuration, so self-preference bias can't be excluded.

**Length and volume.** BabelJudge lists trajectory-length bias (preferring the longer trajectory regardless of added value), hallucination blindness (missing a call to a tool that was never defined), and argument blindness (missing wrong argument values). A 2026 study on AppWorld coding-agent trajectories found judges treated longer, more complex API call sequences as evidence of success, even when the agent only read state and then claimed completion.

**Position bias.** This is mostly measured on text, not trajectories. A practitioner guide says it's mitigated by running both orders and keeping only agreeing verdicts, with the disagreement rate doubling as a reliability metric. I found no trajectory-specific numbers.

**Believing the agent.** This is the largest effect I found for coding. On 9,876 τ²-bench trajectories, no judge configuration exceeded AUROC 0.65, and confident closing language raised "completed" scores by 0.27–0.36 regardless of outcome. On AppWorld coding-agent runs, the best judge reached AUROC 0.537, while a simple task-disjoint detector reached 0.953. AgentRewardBench similarly found judges tend to accept an agent's own reasoning even when it's wrong.

**Outcome-only judging.** In a fault-injection test, an outcome-only judge's recall on faults that leave the reply unchanged equaled its flag rate on clean runs, so paired discrimination was zero. Judges also vary on SWE tasks specifically: a Lean-verification comparison found LLM judgments on SWE tasks showed weak alignment with both formal verification and empirical performance.

**Unstable rubrics.** An audit of tool-calling benchmarks found LLM-judge benchmarks suffer from stochastic rubric generation, judge variance, and hallucinated evaluations.

## Mitigations and how much evidence backs them

- **Execution checks plus trajectory-aware judges (strongest).** Neither alone suffices. A deterministic rule checker had 1.00 loud recall but 0.43 silent recall, while a judge shown every step reached 0.77 silent recall with no false alarms. A 2026 SE-judge audit says to trigger verification such as compilation, static analysis, or tests when a judge can't be trusted.
- **Judge as auditor, not grader of record.** DeepSWE gave its judge the task, the trajectory, verifier output and the hidden reference solution, and the judge found real cheating: about 13% of Opus 4.6 and 4.7 SWE-Bench Pro trials were tagged CHEATED. The authors stress it measures disagreement between two readers, not ground-truth error.
- **Reference answers (mixed).** A survey of code judges says providing a reference code does not generally improve code evaluation performance. References seem most useful for targeted checks like leak and cheating detection.
- **Checklists (helps consistency, not blindness).** CheckEval reports improved rating reliability from decomposed binary questions across 12 evaluator models. But on false-success detection, a checklist prompt didn't rescue the judge (AUROC 0.537 above). One prompt-controlled QA study found a holistic judge matched or exceeded an atomic-decomposition judge on two of three benchmarks, so test it on your tasks.
- **Pairwise comparison.** The same guide says pairwise asks a relative question models answer far more consistently, and it's the workhorse for regression testing. It needs order-swapping, and I found no evidence for it on coding trajectories specifically.
- **Judge ensembles (depends what kind).** Cohere's PoLL found a panel of smaller models from disjoint families outperformed a single large judge, with less intra-model bias and over seven times lower cost. But majority-voting three samples of one model added roughly triple the cost with no measurable gain. My reading is that cross-family diversity addresses self-preference, while same-model voting only reduces sampling noise. That's an inference, not a tested comparison.
- **Hide the agent's narrative.** The best τ²-bench cell was the one with the closing message removed. Judging the diff, test results and tool calls rather than the agent's summary follows from that.
- **Cheap calibrated detectors for triage.** A TF-IDF classifier ran about 3,300× faster than a judge API call, and 50–100 labeled examples per class improved cross-domain AUROC. Even so, it had about 50% precision at a 10% flag rate.

## How to validate a judge (applies to any of the above)
- Report paired discrimination and false alarms on clean runs, not recall alone.
- Freeze the rubric rather than regenerating it per run.
- Re-grade with a different model family to test for self-preference.
- Report agreement with your own hand-labels, using small samples with wide intervals.

## For your setup (my suggestions)
Use tests plus log-derived checks as the base layer, and a trajectory-aware judge from a different family than the agent for approach and scope questions. Give it the diff, test output and tool calls, and withhold the agent's closing summary. Run pairwise comparisons in both orders, and hand-label about 30–50 trajectories to measure your own judge's agreement.

Sources:
- [Self-Preference Bias in LLM-as-a-Judge](https://arxiv.org/pdf/2410.21819)
- [Self-preference in rubric-based evaluation](https://arxiv.org/pdf/2604.06996)
- [Self-preference as measurement artifact (EMNLP Findings 2026)](https://aclanthology.org/2026.findings-emnlp.1571.pdf)
- [BabelJudge](https://arxiv.org/pdf/2606.22329)
- [False success in LLM agents](https://arxiv.org/html/2606.09863)
- [trajectory-judge](https://arxiv.org/pdf/2609.00038)
- [DeepSWE](https://arxiv.org/pdf/2607.07946)
- [AgentRewardBench](https://arxiv.org/html/2504.08942v2)
- [Lean4Agent](https://arxiv.org/pdf/2606.06523)
- [Bias in the Loop](https://arxiv.org/html/2604.16790)
- [Benchmarking the Benchmarks](https://www.alphaxiv.org/abs/2607.02577)
- [PoLL (Cohere)](https://arxiv.org/abs/2404.18796v2)
- [CheckEval](https://arxiv.org/pdf/2403.18771v2)
- [Atomic vs holistic judges](https://www.opentrain.ai/tools/hf-eval-papers/paper/98890387-7b4f-4efc-be30-5173dc0c25d3/)
- [From Code to Courtroom](https://arxiv.org/pdf/2503.02246)
- [LLM-as-Judge for Agents](https://agentic-ai-wiki.vercel.app/operations/evaluation-and-observability/llm-as-judge-for-agents/) (practitioner guide, not peer-reviewed)

## 9, Which coding-agent CLIs (Claude Code, Codex CLI, OpenCode, etc.) can be pointed at a local OpenAI-compatible endpoint (llama.cpp, vLLM, Ollama), and what are the known problems with tool-calling formats when doing so?

Looking up the current state of local-endpoint support per CLI and the tool-calling problems people report.

Every major coding CLI can be pointed at a local server. What differs is which wire protocol it requires, and the failures usually come from the serving stack (chat template, tool parser), not the model. Most of the evidence below is from blogs, issue trackers and gists, so treat version-specific details as snapshots.

## Per-CLI status

**Claude Code** speaks the Anthropic Messages API, set via `ANTHROPIC_BASE_URL`.
- Server support: Ollama v0.14.0 and later are compatible with the Anthropic Messages API, LM Studio added a native /v1/messages endpoint in 0.4.1, and vLLM implements the Messages API too. llama-server serves POST /v1/messages with SSE streaming.
- Map the model tiers: vLLM's docs set ANTHROPIC_DEFAULT_OPUS_MODEL, SONNET_MODEL and HAIKU_MODEL to your model name. Unmapped tiers give 404s.
- Hidden traffic: one author found Claude Code sends housekeeping Haiku requests (37 in one session) that all land on your local server. On a single-slot llama-server these arrived in parallel with the real request and crashed it. His workaround was a proxy plus `--parallel 1`. Another source says llama.cpp does offer count_tokens, so that may be fixed in newer builds.
- Prompt size: the same author measured roughly 25K tokens of tool definitions, versus about 10K for OpenCode, so the first turn is slow (350s versus about 100s for OpenCode on his huge model) and later turns are fast once the prefix is cached.
- Context and backend quirks: 32K is the floor and 64K the sweet spot. Ollama's compatibility layer has no prompt caching and ignores `tool_choice`. A 422 "Extra inputs are not permitted" means the backend rejects Anthropic-specific fields.

**Codex CLI** requires the Responses API now, which is the biggest friction for local setups.
- Codex deprecated the chat completions wire protocol in December 2025 and removed it in February 2026, and much of the ecosystem at the time, Ollama, vLLM and LiteLLM among them, spoke only chat completions.
- Ollama and LM Studio work through `--oss`. llama.cpp initially failed with "'type' of tool must be 'function'". A PR to skip unsupported Responses tools was merged May 15, 2026, so recent builds should work.
- MCP tools: a source-reading analysis (not a lab run) says Ollama 0.34+ and vLLM 0.25+ handle MCP tools correctly, while llama-server drops them silently. Older Ollama returns calls without the namespace, producing "unsupported call".
- Smaller gotchas: the patch tool is a freeform custom tool that the fallback metadata for unrecognized local models omits, and Codex's fallback assumes a 272,000-token window, so set `model_context_window`.
- Chat-only servers need a translating gateway such as LiteLLM, mimo2codex or open-responses-server.

**OpenCode** is the most flexible. It uses `@ai-sdk/openai-compatible` against any chat-completions endpoint. Its problems are client-side strictness:
- Streaming chunks: vLLM, LM Studio and llama.cpp send `function.name: null` in streaming tool-call chunks, causing "Expected 'function.name' to be a string" (there's a PR for this).
- Tool calls as text: stock OpenCode can't recover when a local model returns tool calls as plain JSON text.
- Reports of hangs with a local Ollama provider on simple prompts.

**Others:** Qwen Code supports OpenAI, Anthropic and Gemini-compatible APIs. Aider, Cline, Goose and Crush are described as model-agnostic in roundups, but I didn't verify local-endpoint behavior for them. I also didn't verify whether Gemini CLI accepts local endpoints.

## Tool-calling problems that cut across all of them

1. **The server must convert the model's native format into structured `tool_calls`.** Failures are often silent: the model replies in prose and nothing happens, with no error. The usual causes are vLLM missing `--enable-auto-tool-choice` or the wrong `--tool-call-parser`, and llama.cpp missing `--jinja`.
2. **Parser and template mismatches per model family.** Examples: on vLLM, `--tool-call-parser hermes` silently fails for Qwen 2.5 Coder. A fixed Qwen template notes vLLM's qwen3_coder parser expects XML while llama.cpp's Hermes-style parsers can't parse it, so llama.cpp users get silently dropped tool calls. Gemma 4 was broken in Ollama v0.20.0 (parser failure, streaming dropped tool calls), and DeepSeek V4 Flash emitted valid tool calls that local agent runners could not parse until a llama.cpp fix.
3. **Template bugs, not just parser bugs.** In vLLM's Kimi K2 debugging, the issue was clearly in how vLLM was using the chat template. A bundled template can be too strict for Codex message ordering, so you provide your own via `--chat-template-file`.
4. **Reasoning models.** One guide says output can land in `reasoning_content` instead of `content`, so the agent sees an empty reply. It lists disabling thinking as the fix.
5. **Streaming delta parsing.** One diagnosis lists streaming delta parsers and client-side parsers that miss calls the backend did return as separate failure layers.
6. **Loops.** Malformed calls fed back into history cause self-reinforcing loops.
7. **Sampler settings.** One guide says default temperature causes thinking loops and malformed calls, so use the model author's recommended values.

## Implication for your benchmarks (my suggestion)
A bad tool-call stack looks like a bad model. Record the server version, chat template, parser, sampler settings and context size as part of each benchmark config. Run a one-tool smoke test before every campaign so a parser failure doesn't get scored as a model failure. For Codex, check the backend's MCP and tool-type handling before comparing it against other CLIs.

Sources:
- [Ollama Anthropic compatibility](https://registry.ollama.ai/blog/claude)
- [vLLM Claude Code integration](https://docs.vllm.ai/en/v0.16.0/serving/integrations/claude_code/)
- [Claude Code with local LLMs guide](https://dev.to/reneza/claude-code-with-local-llms-and-anthropicbaseurl-ollama-lm-studio-llamacpp-vllm-1g6j)
- [KDnuggets: Pairing Claude Code with Local Models](https://kdnuggets.com/pairing-claude-code-with-local-models)
- [The Ghost in the CLI](https://dev.to/mfolsom/the-ghost-in-the-cli-why-claude-code-kills-local-inference-dfc)
- [Codex custom providers guide](https://codex.danielvaughan.com/2026/04/23/codex-cli-custom-model-providers-configuration-guide/)
- [Codex router (wire_api removal)](https://opper.ai/blog/codex-router)
- [Codex MCP tools on local backends](https://particula.tech/blog/codex-cli-local-model-mcp-tools)
- [llama.cpp PR #23041](https://github.com/ggml-org/llama.cpp/pull/23041)
- [Codex/llama.cpp Responses failure report](https://www.goodfirstissue.org/unslothai/unsloth/issues/5141)
- [OpenCode streaming name:null PR](https://github.com/anomalyco/opencode/pull/26433)
- [OpenCode + Gemma 4 on llama.cpp](https://gist.github.com/daniel-farina/87dc1c394b94e45bb700d27e9ea03193)
- [OpenCode Ollama hang](https://github.com/anomalyco/opencode/issues/22132)
- [Gemma 4 tool-calling layers](https://discuss.huggingface.co/t/gemma-4-bug-fixes-and-research-request/176979)
- [vLLM tool calling docs](https://docs.vllm.ai/features/tool_calling.html)
- [Kimi K2 on vLLM](https://vllm.ai/blog/2025-10-28-kimi-k2-accuracy)
- [Qwen Fixed Chat Templates discussion](https://huggingface.co/froggeric/Qwen-Fixed-Chat-Templates/discussions/52)
- [Terminal coding CLIs compared](https://inventivehq.com/blog/terminal-ai-coding-clis-compared-2026)
