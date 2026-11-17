# Spec Delta

## Purpose

Extracts candidate task episodes from local agent session histories so real day-to-day work can be turned into benchmark tasks, without modifying or leaking the source histories.

## ADDED Requirements

### Requirement: Supported session sources
The miner SHALL read sessions from Codex (`~/.codex/sessions`), Claude Code (`~/.claude/projects`), Hermes (`~/.hermes/state.db`) and Oh My Pi (`~/.omp/agent/sessions`).

#### Scenario: All four sources
- **WHEN** the miner runs with default settings
- **THEN** its output includes candidates from each source that has sessions for the selected repos, and reports a session count per source

### Requirement: Sources are read-only
The miner SHALL NOT write to, lock, or modify any source session file or database. SQLite sources SHALL be opened read-only.

#### Scenario: Hermes in use
- **WHEN** the miner runs while Hermes is running and writing to its database
- **THEN** the miner reads a consistent snapshot and Hermes is unaffected

### Requirement: Subagent and automated sessions excluded
The miner SHALL skip sessions that have no human request, such as subagent threads and automated reviewer runs, and SHALL report how many it skipped.

#### Scenario: Codex subagent thread
- **WHEN** a Codex session's metadata marks it as a subagent thread
- **THEN** it does not appear as a candidate

### Requirement: Repo filter
The miner SHALL accept a list of repos and SHALL only emit candidates whose working directory is inside one of them.

#### Scenario: Priority repos only
- **WHEN** the miner runs with repos `sd-scripts` and `hcom`
- **THEN** no candidate from any other directory appears in the output

### Requirement: Candidate record contents
Each candidate SHALL contain: source and session id, line or message references, repo, starting commit (or `unknown`), the user's request, later user corrections, outcome signals (files changed, commits made, tests run, how the session ended), and a suggested track (coding or investigative).

#### Scenario: Commit recovered from timestamp
- **WHEN** a session records branch and start time but no commit
- **THEN** the miner finds the commit on that branch at that time from the repo's git history and marks it as inferred

#### Scenario: No recoverable commit
- **WHEN** the repo state at session start cannot be determined
- **THEN** the candidate is still listed, with starting commit `unknown`

### Requirement: Secrets redacted
The miner SHALL scan its output for secrets and SHALL redact any it finds before writing. The output SHALL record how many secrets were redacted.

#### Scenario: API key in a transcript
- **WHEN** a user message contains an API key
- **THEN** the candidate list shows the message with the key replaced by a redaction marker

### Requirement: Output is reviewable
The miner SHALL write candidates to a human-readable file for review, plus a machine-readable file with the same records. Output SHALL stay local and out of version control.

#### Scenario: Review file
- **WHEN** the miner finishes
- **THEN** a candidates file exists with one row per candidate and a summary of counts by repo, source and track
