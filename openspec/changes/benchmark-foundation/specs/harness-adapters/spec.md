# Spec Delta

## Purpose

Defines how each in-scope agent harness (Codex, Claude Code, OpenCode, Hermes, Oh My Pi) is installed, pinned, pointed at a model, run without a human, and how its trajectory and usage are captured for scoring.

## ADDED Requirements

### Requirement: Five harnesses supported
The benchmark SHALL be able to run tasks with each of these harnesses: Codex CLI, Claude Code, OpenCode, Hermes, Oh My Pi.

#### Scenario: Each harness completes a smoke task
- **WHEN** the smoke task is run once with each of the five harnesses against a hosted model
- **THEN** each trial finishes without an infrastructure error and has a verifier result

### Requirement: Harness version is pinned
Each adapter SHALL install a specific, recorded version of its harness inside the sandbox rather than whatever is latest at run time.

#### Scenario: Version recorded
- **WHEN** a trial runs with any harness
- **THEN** the trial record contains the exact harness version that ran

### Requirement: Harness runs without a human
Each adapter SHALL run its harness headless, with permissions set so it never waits for approval, and SHALL end the trial when the harness exits or the task timeout is reached.

#### Scenario: Harness asks for approval
- **WHEN** the harness would normally prompt for approval of a command
- **THEN** the command proceeds without waiting, and the trial does not hang

### Requirement: Hosted and local models
Each adapter SHALL accept a model from a hosted provider or from a local endpoint, using the wire protocol that harness requires. An adapter SHALL declare which protocols it supports.

#### Scenario: Local endpoint
- **WHEN** a configuration points Claude Code at a local llama.cpp endpoint serving the Anthropic Messages protocol
- **THEN** all of the harness's model calls go to that endpoint, including background or auxiliary calls

#### Scenario: Unsupported protocol
- **WHEN** a configuration points a harness at an endpoint that does not speak a protocol the adapter supports
- **THEN** the runner refuses the configuration before any trial starts

### Requirement: Trajectory and usage captured
Each adapter SHALL save the harness's native session log and SHALL produce a normalized trajectory listing each model turn, each tool call with its arguments and result status, and token usage. Cost SHALL be recorded when the provider reports it, or computed from a price table otherwise.

#### Scenario: Tool calls counted
- **WHEN** a trial finishes
- **THEN** the normalized trajectory lists every tool call the agent made, in order, with its name and whether it succeeded

#### Scenario: Usage missing
- **WHEN** a harness or endpoint reports no token usage
- **THEN** the trial records usage as unknown rather than zero

### Requirement: User config does not leak into trials
Adapters SHALL NOT copy the host user's harness configuration, memories, skills, hooks, MCP servers or instruction files into the sandbox. Only what the arm and toolkit specify SHALL be added.

#### Scenario: Host memories absent
- **WHEN** a trial runs Hermes or Codex under arm `stock`
- **THEN** none of the host's memories, AGENTS.md, skills or hooks are present in the sandbox

### Requirement: Toolkit items wired into each harness
Each adapter SHALL make every toolkit item usable through its harness's own mechanism (MCP server registration, skills location, executables on PATH). An item a harness cannot support SHALL cause the configuration to be refused before any trial starts.

#### Scenario: MCP server available
- **WHEN** a trial runs with a toolkit containing the codebase-memory MCP server
- **THEN** the harness lists the server's tools and a call to one of them succeeds

#### Scenario: Unsupported item
- **WHEN** a toolkit contains skills and the harness has no skills mechanism
- **THEN** the runner refuses that configuration and names the unsupported item
