# Task coverage tagging

Every task in either track (internal or external) gets one `[[task]]` entry in `candidates.toml`. `grid.py` uses those entries to show what the internal track covers, which cells are thin, and which external candidates could fill those cells.

```
python docs/external-tasks/grid.py docs/external-tasks/candidates.toml          # full report
python docs/external-tasks/grid.py docs/external-tasks/candidates.toml --min 2  # call a cell thin if it has fewer than 2 internal tasks
```

The script uses only the standard library (`tomllib`), so it needs Python 3.11 or later.

## Fields

| Field | Required | Values |
|---|---|---|
| `id` | yes | Unique ID. External tasks keep their candidate IDs (C02 and so on). Internal tasks use something like `I-<repo>-<n>`. |
| `track` | yes | `internal` or `external` |
| `repo` | yes | Source repository |
| `title` | yes | One line |
| `pattern` | yes | The **primary** work pattern: one of `bugfix`, `feature`, `refactor`, `perf`, `investigation`, `review`, `design`, `docs` |
| `domains` | yes | One or more of the domains listed below |
| `languages` | yes | e.g. `python`, `rust`, `cpp`, `typescript`, `cuda` |
| `env` | yes | `cpu`, `gpu-optional` or `gpu-required` |
| `setup` | yes | Setup cost from 1 (light) to 5 (heavy) |
| `grading` | yes | `existing_tests`, `new_test`, `checkable_answer` or `judge_only` |
| `demands` | no | What the task makes the agent do (list below) |
| `familiarity` | no | How well you know the code: `own-code`, `own-domain` (your domain, someone else's repo) or `unfamiliar` |
| `evidence` | yes | `validated`: nop and oracle checks run on the real variant. `probed`: the behavior the task depends on was observed on upstream. `adjacent`: only a related path was exercised. `source`: read, never run. |
| `contamination` | no | Public-event risk: `low`, `medium` or `high` |
| `status` | yes | `pilot`, `pilot-pending`, `active`, `hold`, `reserve`, `calibration`, `deferred`, `dropped`, `lead` |
| `notes` | no | Free text |

### Domains

| Domain | Covers |
|---|---|
| `ml-compiler` | Graph capture, lowering and codegen (Inductor, Triton, TorchAO, tinygrad) |
| `ml-runtime` | Inference and serving state, KV caches, CUDA graphs, sequence state |
| `ml-training` | Trainers, checkpointing, hooks, optimizers, distributed training |
| `compiler-ir` | General IR, passes, rewriting and parsing (xDSL, MLIR, egg, Cranelift) |
| `native-interop` | Python↔Rust/C++ bindings, ABIs, buffer ownership, free-threading |
| `concurrency` | Async code, threads, process scheduling, distributed coordination |
| `build-tooling` | Build systems, packaging, toolchains, test runners, plugin hosts |
| `agent-infra` | Agent runtimes, tool protocols, permissions, sandboxing, checkpoints, memory |
| `data-storage` | Storage formats, query engines, provenance, databases |
| `dev-env` | Nix, containers, environment and config management |
| `numerics` | Numerical correctness, array semantics |
| `web-app` | Frontend and backend application work |

Add a domain to `DOMAINS` in `grid.py` if you need one. Entries that use a domain the script doesn't know trigger a warning but still count.

### Demands

`reproduce` · `trace-cross-boundary` · `unfamiliar-codebase` · `ambiguous-spec` · `judge-claims` · `native-build` · `long-horizon` · `measure-not-read` (the answer needs an instrumented run, not just reading the code)

## How to read the report

1. **Pattern × domain grid.** Each cell shows `I:n E:m`, meaning n internal tasks and m live external tasks. Tasks with status `dropped` or `lead` aren't counted.
2. **Gaps.** Lists the cells where the internal count is below `--min` and gives the external candidates that could fill each one, ordered by evidence and status. An external task goes into the suite only if it fills a gap *and* its evidence is at least `probed`.
3. **Marginals.** Counts by language, environment, grading and demands. Check how much of the suite relies on `checkable_answer` and `judge_only`. If most of it does, judge reliability becomes the bottleneck.

Tag each internal task when you finish authoring it. For each one, decide the primary pattern by what the agent mostly has to *do*, not by the commit that inspired it.
