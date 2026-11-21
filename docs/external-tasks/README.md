# External tasks

These are benchmark tasks built on public upstream repos, as opposed to tasks mined from our own sessions. The source material is an external research pass:
- **20 Nov 2026:** an audit scored 48 candidates, C01–C48.
- **21 Nov 2026:** a first batch of seven tasks (C02, C04, C13, C35, C37, C45, C48) was written and checked on another machine (Bubblewrap, no network).

Porting the batch into this repo's Harbor/Podman task format is the OpenSpec change [`external-task-track`](../../openspec/changes/external-task-track/), tracked by bead `fitting-room-841`.

## What's here (safe to publish)

| File | What it is |
|---|---|
| [task-coverage.md](task-coverage.md) | Coverage tag fields and vocabularies, and how to read the grid report |
| [candidates.toml](candidates.toml) | Coverage tags for the C01–C48 candidates |
| [grid.py](grid.py) | Pattern × domain coverage report: `python docs/external-tasks/grid.py docs/external-tasks/candidates.toml` |
| [index.md](index.md) | Candidate index: repository, title, area, baseline evidence |
| [scores.md](scores.md) | Six-axis score matrix, plus public-event and variant risk |
| [runtime/](runtime/) | How batch 01 was staged on the original machine: pins (`environment.lock`, `requirements-*.txt`) and the Bubblewrap runner. Reference only, since this repo runs trials under Podman. |

Batch-01 recommendation: C35, C02, C45, C37, C04, C13, C48. C06 and C08 are the strongest alternates. C10 and C16 were dropped; C11 and C14 were deferred.

## What's not here (private, local only)

This repo is public. Anything that reveals an answer would spoil a task for models trained on public code, so it stays out of git. It lives in the gitignored `work/domain-tasks/`:

| Path | Contents |
|---|---|
| `archive/` | The original zips and the baseline research report, byte for byte |
| `private/audit/` | Full audit: README with the per-candidate rationale, contamination controls, per-candidate `candidate.md` / `task-draft.md` / `author.md` / `feasibility.md`, probe logs |
| `private/author/<id>/` | Batch-01 author material: reports, oracle, alternative, near-miss, expected answers, verifiers, `staging.json` digests, validation runs |
| `private/trials/<id>/` | Batch-01 trial trees as the agent sees them. These contain no answers, but they bundle upstream source (37 MB). The port materializes them from upstream clones instead. |
| `private/runtime/` | Same as `runtime/` above |

`work/` has no git backup, so keep a copy of `work/domain-tasks/archive/` somewhere off-repo. Never mount anything from `work/domain-tasks/` into a trial.
