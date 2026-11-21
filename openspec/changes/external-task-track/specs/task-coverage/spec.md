# Spec Delta

## Purpose

Tags every task and candidate with what it covers, so the user can see which pattern × domain cells the internal track leaves thin and which external candidates could fill them.

## ADDED Requirements

### Requirement: Every task carries coverage tags
Each task in `tasks/` SHALL declare coverage tags in its metadata: id, track, repo, pattern, domains, languages, env, setup, grading, evidence and status. It MAY also declare demands, familiarity and contamination. Values SHALL come from the documented vocabularies.

#### Scenario: Missing tag
- **WHEN** a task's metadata has no `pattern`
- **THEN** the coverage report lists the task as skipped with the missing fields, and validation of that task fails

#### Scenario: Unknown domain
- **WHEN** a task uses a domain that isn't in the vocabulary
- **THEN** the report warns and counts the task under that domain

### Requirement: Candidate register
Candidates that are not yet authored tasks SHALL be kept in a tracked register with the same tags. The register SHALL hold no answers. When a candidate becomes a task, the task keeps the candidate's id, and the register entry points to the task.

#### Scenario: Candidate authored
- **WHEN** C45 is ported into `tasks/`
- **THEN** the report counts C45 once, from the task, and the register entry is marked as authored

### Requirement: Coverage report
`fr tasks grid` SHALL print a pattern × domain grid of internal and live external counts. It SHALL also list thin cells together with the external candidates that could fill them, ordered by evidence and then by status. It SHALL print marginals by pattern, language, env, grading, evidence, demands and familiarity. Tasks with status `dropped` or `lead` SHALL NOT be counted.

#### Scenario: Thin cell
- **WHEN** `fr tasks grid --min 2` runs and `agent-infra / investigation` has no internal tasks
- **THEN** the gap list shows that cell with C45, C48 and C44, each with its evidence and status

#### Scenario: Judge reliance
- **WHEN** the report runs
- **THEN** it states how many live tasks are graded by answer or judge rather than by tests

### Requirement: Fill rule for external tasks
An external candidate SHALL be proposed for authoring only if it fills a thin cell and its evidence is at least `probed`. Candidates outside the rule MAY still be authored when the user explicitly chooses them.

#### Scenario: Source-only candidate
- **WHEN** a thin cell's only filler has evidence `source`
- **THEN** the report shows it as a filler but marks it as below the fill rule
