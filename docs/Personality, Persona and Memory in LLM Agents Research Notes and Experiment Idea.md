# Personality, Persona and Memory in LLM Agents: Research Notes and Experiment Ideas

Nov 17, 2026 · @hoshino imi

## Summary

Personality and persona prompts measurably change how LLMs behave, but they rarely raise task accuracy. No one has yet tested how an agent with a rich character and memories works compared with one running only the base harness instructions.

- **Persona prompts:** generic personas give no or slightly negative accuracy effects; task-matched personas helped code generation in one study.
- **Personality traits:** Big Five traits shift capability, safety scores and team dynamics, and the effects depend on task structure.
- **Harness versus model:** the same model can score about 10 points apart across harnesses, so instructions and tooling matter as much as weights.
- **The open question:** whether a model that carries its own character and memories into everyday work behaves differently from a blank one, in how it explores, verifies, disagrees and reports.

## What the research says

Personality effects on LLMs are real but task-dependent: they move behavior and safety scores more than accuracy, and in the one coding study that compared model strength, mid-tier models gained most.

| Strand | Finding | Source |
| --- | --- | --- |
| Generic persona prompts | 162 social roles in system prompts gave no or small negative effects on accuracy; each persona's effect was largely random | [Zheng et al.](https://arxiv.org/html/2311.10054v3) |
| Task-matched personas for code | A programmer personality generated per task raised pass rates in 23 of 28 model-dataset combinations, best gain 12.9%; mid-tier models gained most | [Personality-Guided Code Generation](https://arxiv.org/html/2411.00006v2) |
| Measurability | Larger instruction-tuned models show reliable, controllable personality profiles that influence generation | [Personality Traits in Large Language Models](https://arxiv.org/pdf/2307.00184) |
| Big Five and cognition | Neuron-level trait induction shifted six benchmarks; Openness and Extraversion mattered most; 73.68% of effect directions matched human findings | [Chen et al.](https://arxiv.org/abs/2604.11048) |
| Big Five and safety | Low Conscientiousness cost roughly 20-40 points on safety tasks; a low-agreeableness, low-conscientiousness, high-neuroticism profile cut ETHICS-CM by 26.4 points for GPT-4 with under 3 points lost on MMLU | [Psychometric Personality Shaping](https://arxiv.org/html/2509.16332v1) |
| Multi-agent teams | Low agreeableness changed communication a lot but barely affected coding milestones; it degraded research collaboration and bargaining | [Keluskar et al.](https://arxiv.org/abs/2606.27443) |
| Writing and ideation | Plot ideas from one persona were near-identical (similarity 0.92); across personas they varied widely (0.20) | [Wan and Kalman](https://arxiv.org/abs/2504.13868v1) |
| The model's own character | Persona vectors track and steer traits such as sycophancy; misaligned-persona features mediate emergent misalignment; the Assistant Axis shows drift, and activation capping cut harmful responses about 50% | [Anthropic](https://www.anthropic.com/news/persona-vectors), [OpenAI](https://openai.com/index/emergent-misalignment/), [Assistant Axis](https://www.anthropic.com/research/assistant-axis) |
|  |  |  |

One pattern recurs: structured tasks with formal checks, such as coding with tests, absorb personality effects better than open-ended collaboration.

## Model versus harness

How an agent is wrapped often matters as much as which model it runs, and the sizes involved dwarf typical gaps between frontier models.

- On SWE-bench Pro, Claude Opus 4.5 scored 45.9% under the standardized SEAL scaffold and 55.4% under Claude Code ([source](https://arxiv.org/pdf/2605.23950)).
- Changing only the harness raised Terminal-Bench 2 pass@1 from 69.7% to 77.0%, and monitoring reports up to 15 points of scaffold-only variation on SWE-bench Verified ([source](https://www.alphaxiv.org/abs/2605.23950)).
- Some of these numbers mix vendor and independent runs, so treat them as directional.

No study found separates the default character of a frontier model from the instructions around it. Base versus RLHF cannot be tested on closed models, but the default Assistant persona can be compared against stripped or overridden system prompts in the same harness.

## Customization surfaces

Both Claude Code and Codex let you change the system prompt or add instructions, so persona and instruction conditions can be tested directly in each.

| Harness | Surface | Effect |
| --- | --- | --- |
| Claude Code | `--append-system-prompt` | Adds text to the end of the default system prompt ([CLI reference](https://glama.ai/mcp/servers/@florinel-chis/voiceflow-doc-mcp/blob/dd1eccac05536155da291f9fb61c82caa8b32f16/data/claude_code_docs/docs-en-cli-reference.md)) |
| Claude Code | `--system-prompt` | Replaces the entire system prompt |
| Claude Code | Output styles | Modify the system prompt; custom styles drop the default software-engineering instructions unless told to keep them ([docs](https://docs.anthropic.com/en/docs/claude-code/output-styles)) |
| Claude Code | `CLAUDE.md` | Added as a user message after the system prompt, so placement differs from the options above |
| Codex | `developer_instructions` in `config.toml` | Injects text into the system prompt without editing repo files ([overview](https://codex.danielvaughan.com/2026/05/07/codex-cli-instruction-stack-six-surfaces-agents-md-rules-hooks-skills/)) |
| Codex | `AGENTS.md` | Project and personal guidance, loaded separately from the system prompt |
| Codex | Personality picker | Reportedly removed in 0.156.0 (September 2026), per a [third-party report](https://www.memorylake.ai/en/blogs/codex-personality); verify against current docs |

Where an instruction sits (system prompt or user message) is a confound to control in any comparison.

## The open question: character and memory during work

The interesting question is how a model that carries a detailed personality and memories into ordinary work compares with one running only the base harness instructions, once the situation is allowed to set the register, serious when stakes are high.

Three bodies of evidence sit nearby, none of them direct:

- **Extra context changes behavior more than outcomes.** A large study of `AGENTS.md`-style context files found agents follow them and explore more, with [more thorough testing and file traversal](https://iclr.cc/virtual/2026/10021142), but success rates did not generally improve while [inference cost rose over 20%](https://www.opentrain.ai/papers/evaluating-agents-md-are-repository-level-context-files-helpful-for-coding-agent--arxiv-2602.11988/).
- **Memory about the user pushes toward agreement.** In a two-week study, [user memory profiles produced the largest increases in agreement sycophancy](https://arxiv.org/html/2509.12517v3), up to +45% for one model. That was chat, not agentic work.
- **Memories steer outputs.** Agents show an [experience-following property](https://arxiv.org/abs/2505.16067): similar past records produce similar outputs, which can propagate old errors.

Persona fidelity research adds a caution. In extended interactions, [fidelity fades and persona-assigned models initially trail baselines on instruction following](https://arxiv.org/html/2512.12775v2), and earlier work measured [significant persona drift within eight rounds](https://www.catalyzex.com/paper/arxiv:2402.10962).

**Hypothesis.** Pass rates stay roughly flat. Cost, exploration depth, willingness to push back on a flawed request, and honesty of the final report are where the arms would differ.

**Subagents.** If a persona'd main agent only coordinates and verifies, character may matter little for the work itself but still leaks through delegation messages, since the [orchestrator-to-subagent interface is a prompt](https://arxiv.org/pdf/2604.11548) each subagent interprets in its own context.

**What is unmeasured.** Existing work asks whether the persona survives. The question here is whether the working standards survive: style and standards are separable, and no study found separates them.

## Experiment designs

Four experiments, each runnable on your own repos with the same tasks across arms and several runs per cell to absorb variance.

| Experiment | Conditions | What it answers |
| --- | --- | --- |
| 1. Model versus harness | Claude and GPT models, each in Claude Code and Codex (optionally crossed), under default prompt versus minimal prompt with the same tools | How much performance is the model, how much the wrapper |
| 2. Character and memory | Base harness; persona only; memory only (including facts about you); persona plus memory | How a model with its own character and memories compares to a blank one |
| 3. Trait versus directive | Trait descriptions ("meticulous", "impatient") with no behavioral commands, versus explicit directives ("run tests before finishing") | Whether character does anything beyond explicit instruction |
| 4. Subagent delegation | Persona'd orchestrator with plain subagents; plain orchestrator with a persona'd verifier | Where character matters, and whether it leaks through delegation messages |

**Measures beyond pass rate:**

- Tool-call mix, and whether tests run before the agent declares done
- Clarifying questions asked versus assumptions made
- Diff size and scope creep
- Tokens, wall time and retries after failure
- Whether the final report matches what was actually done

**Seeded-flaw tasks.** Add tasks with a planted problem, such as a wrong assumption in the request or a spec that conflicts with the codebase, and count whether the agent flags it or builds on it. These are the most likely place for the arms to separate, and they test the honest-colleague quality directly.

**Style versus standards.** For graded stakes (a destructive migration, a production-adjacent command, a security-sensitive change, a failing test that could be skipped), score behavior separately from tone: confirms before destructive steps, reports failures honestly, runs verification. The interesting result is whether serious-mode standards appear unprompted when stakes rise.

## Gaps and caveats

Most evidence here is recent preprints read from abstracts and excerpts, so effect sizes are indicative rather than settled.

- Only the multi-agent team paper and the psychometric shaping paper were opened beyond search excerpts; the rest rely on abstracts, summaries and press pages.
- Several studies use older or mid-size models; frontier-model results, especially for long-horizon agentic coding, are largely missing.
- Generic personas hurt or do nothing while task-matched personas helped code generation; the difference is probably task matching, but this is an inference.
- The sycophancy-with-memory study is chat-based, and the Assistant Axis work used open-weight models.
- Harness comparisons mix vendor and independent runs, and the Codex personality change comes from a third-party blog.
- One orchestrator-refusal anecdote (a blog post) suggests delegation framing can change behavior; it is not a controlled result.

## Sources

Personas and personality:

- [When "A Helpful Assistant" Is Not Really Helpful](https://arxiv.org/html/2311.10054v3)
- [Personality-Guided Code Generation Using LLMs](https://arxiv.org/html/2411.00006v2)
- [Personality Traits in Large Language Models](https://arxiv.org/pdf/2307.00184)
- [A Systematic Analysis of the Impact of Persona Steering on LLM Capabilities](https://arxiv.org/abs/2604.11048)
- [Psychometric Personality Shaping Modulates Capabilities and Safety](https://arxiv.org/html/2509.16332v1) (opened)
- [When Does Personality Composition Matter for Multi-Agent LLM Teams?](https://arxiv.org/abs/2606.27443) (opened)
- [Using Generative AI Personas Increases Collective Diversity in Human Ideation](https://arxiv.org/abs/2504.13868v1)
- [The Power of Personality: A Human Simulation Perspective](https://arxiv.org/html/2502.20859v1)

Model character, drift and memory:

- [Persona vectors (Anthropic)](https://www.anthropic.com/news/persona-vectors)
- [Persona Features Control Emergent Misalignment (OpenAI)](https://openai.com/index/emergent-misalignment/)
- [The assistant axis (Anthropic)](https://www.anthropic.com/research/assistant-axis)
- [Persistent Personas? Role-Playing, Instruction Following, and Safety in Extended Interactions](https://arxiv.org/html/2512.12775v2)
- [Measuring and Controlling Persona Drift in Language Model Dialogs](https://arxiv.org/pdf/2402.10962v1)
- [Interaction Context Often Increases Sycophancy in LLMs](https://arxiv.org/html/2509.12517v3)
- [How Memory Management Impacts LLM Agents](https://arxiv.org/abs/2505.16067)

Harnesses and context files:

- [Stop Comparing LLM Agents Without Disclosing the Harness](https://arxiv.org/html/2605.23950)
- [Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?](https://arxiv.org/html/2602.11988)
- [Claude Code output styles](https://docs.anthropic.com/en/docs/claude-code/output-styles)
- [Codex CLI instruction stack](https://codex.danielvaughan.com/2026/05/07/codex-cli-instruction-stack-six-surfaces-agents-md-rules-hooks-skills/)
- [SemaClaw: subagents as prompt-defined interfaces](https://arxiv.org/pdf/2604.11548)
- [Quesma: orchestrator talked Claude into refusing](https://quesma.com/blog/tbench-orchestrator-refuses/)
