# Spec Delta

## Purpose

Defines the score dimensions computed for every trial, which are measured directly and which come from an LLM judge, and how the judge is kept honest, so models and harnesses can be compared on more than pass rate.

## ADDED Requirements

### Requirement: Correctness score
Every trial SHALL have a correctness score from the task's verifier: pass/fail for coding and closed-set investigative tasks, and a checklist score for checklist investigative tasks.

#### Scenario: Coding task
- **WHEN** a coding trial ends and the verifier's checks all pass
- **THEN** correctness is recorded as pass, along with the per-check results

### Requirement: Measured efficiency dimensions
Every trial SHALL record, from logs alone: input, output, cached and reasoning tokens; cost; wall time; number of model turns; number of tool calls by tool; failed tool calls; repeated identical tool calls; and whether the agent ran the repo's tests before finishing.

#### Scenario: Repeated calls detected
- **WHEN** an agent runs the same command with the same arguments three times in a row
- **THEN** the trial records two repeated identical calls

#### Scenario: Tests run before finishing
- **WHEN** an agent's last test-suite run happens after its last file edit
- **THEN** the trial records that the agent verified before finishing

### Requirement: Toolkit usage dimension
For each tool in the trial's toolkit, every trial SHALL record from logs whether it was used, how many calls were made, when it was first used, and how many calls failed. A toolkit item can also define its own usage checks, such as an issue created and closed for beads. Trials with toolkit `none` record no toolkit usage.

#### Scenario: Tool provided but ignored
- **WHEN** the codebase-memory MCP server is available and the agent only uses grep and file reads
- **THEN** the trial records codebase-memory as available with zero calls

#### Scenario: Shell-invoked tool counted
- **WHEN** the agent runs `bd create` and later `bd close` through its shell tool
- **THEN** the trial counts both as beads calls, and the beads check for an issue that was created and closed passes

### Requirement: Judged process dimensions
For dimensions logs cannot measure (approach, scope discipline, honesty of the final report, explanation quality, and whether available toolkit tools were used where they fit), the system SHALL use an LLM judge answering a fixed list of yes/no criteria per dimension.

#### Scenario: Scope creep
- **WHEN** an agent changes files unrelated to the request
- **THEN** the judge's scope criterion is recorded as failed, with the files it cited

### Requirement: Judge independence
The judge model SHALL come from a different model family than the agent being judged. The judge SHALL see the instruction, the diff or answer, verifier output and the tool-call trajectory, and SHALL NOT see the agent's closing summary, except for the dimension that checks the summary against what was actually done.

#### Scenario: Judging a Claude run
- **WHEN** the agent model is a Claude model
- **THEN** the judge is a non-Claude model, and its input omits the agent's final message for every criterion except report honesty

### Requirement: Frozen judge setup
The judge model, version, prompt and criteria SHALL be fixed per benchmark version and recorded with each judged score. Changing any of them SHALL create a new judge version, and scores from different judge versions SHALL NOT be mixed.

#### Scenario: Judge prompt edited
- **WHEN** a criterion's wording is changed
- **THEN** the judge version increments and reports keep old and new judged scores apart

### Requirement: Judge calibration against human labels
Before judged dimensions appear in reports, the judge SHALL be compared against at least 30 trials labelled by the user, and the agreement per dimension SHALL be reported. A dimension whose agreement is below the threshold set in the design SHALL be shown as unvalidated.

#### Scenario: Low agreement
- **WHEN** the judge agrees with the user's labels on report honesty in only 60% of trials
- **THEN** reports show report-honesty scores marked unvalidated

### Requirement: Multi-dimension report
Reports SHALL show every dimension separately per configuration, including pass rate with its spread across repeats and cost per passed task, and SHALL NOT collapse them into a single score unless the user asks for a weighted view.

#### Scenario: Compare two configurations
- **WHEN** a user compares a local model in OpenCode against a hosted model in Codex
- **THEN** the report shows correctness, cost, time, tool-use and judged dimensions side by side
