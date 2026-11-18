"""Triage mined episodes as benchmark task material (checkpoint 1 preparation).

The candidate table is too long to pick from by hand. GLM reads each episode (the
request, the follow-ups, what was edited and run, review bugs, labelled shortfalls) and
writes a stand-alone task statement plus the facts needed to choose a representative
set: kind of work, size, how a run could be graded, GPU need, and whether the request
only makes sense with earlier conversation. Selection happens afterwards
(``select_shortlist``); this module never decides what goes into the benchmark.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.error
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fitting_room.miner import classify as cl

PROMPT_VERSION = "triage-v1"
BATCH = 6
WORK_TYPES = (
    "feature", "refactor", "bugfix", "investigation", "explain", "design",
    "config_tooling", "docs", "review", "other",
)  # fmt: skip
GRADING = ("existing_tests", "new_test", "checkable_answer", "judge_only")
SIZES = ("small", "medium", "large")
VERDICTS = ("good", "maybe", "unusable")

SYSTEM = """You help build a benchmark of real software-engineering work from a developer's
AI-agent session history. Each item is one episode: the developer's REQUEST, their later
FOLLOW-UPS, and facts about what the agent did (files edited, test runs, tool calls,
review findings, places where the agent fell short).

The benchmark replays the request against the repository at the episode's starting commit
with a fresh agent, so judge the REQUEST as a task for a new agent with no chat history.

For each item return:
- task: the request rewritten as a stand-alone task statement for a new agent (<= 60
  words). Keep the developer's intent and constraints; do not add a solution.
- work_type: feature | refactor | bugfix | investigation | explain | design |
  config_tooling | docs | review | other  (investigation = find out how/why something
  works or fails; explain = answer a question about the code; design = plan or
  architecture discussion).
- size: small (< 1 hour of focused agent work) | medium | large (many hours or many
  files).
- grading: existing_tests | new_test | checkable_answer | judge_only  (how a replay
  could be graded: the repo's tests already cover it; a hidden test could be written;
  the answer is a fact that can be checked; or only a rubric/LLM judge could say).
- gpu: true if doing or checking the task needs a CUDA GPU.
- needs_history: true if the request cannot be understood without earlier conversation
  ("do that", "continue", "the other one").
- verdict: good | maybe | unusable  (good = clear, self-contained, gradable, not huge).
- why: <= 20 words.

Answer with ONLY a JSON array:
[{"id": "<id>", "task": "...", "work_type": "...", "size": "...", "grading": "...",
  "gpu": false, "needs_history": false, "verdict": "...", "why": "..."}]"""


def triage_key(ep: dict) -> str:
    raw = f"{PROMPT_VERSION}\0{cl.label_version()}\0{ep['episode_id']}\0{ep['request'][:2000]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _render_one(ep: dict) -> str:
    fus = ep.get("follow_ups") or []
    fu_lines = "\n".join(f"- {' '.join(f['text'].split())[:220]}" for f in fus[:6]) or "(none)"
    short = [
        f"- [{f.get('label_kind') or 'shortfall'}] {f.get('label_reason') or ''}"
        for f in fus
        if f.get("label") in cl.SHORTFALL_LABELS
    ]
    bugs = [f"- [{b['label']}] {b.get('bug') or ''}" for b in ep.get("review_bugs") or []]
    return (
        f"### id: {triage_key(ep)}\nrepo: {ep['repo']}\n"
        f"REQUEST:\n{ep['request'][:2000]}\n\n"
        f"FOLLOW-UPS ({len(fus)}):\n{fu_lines}\n\n"
        f"FACTS: {ep['tool_calls']} tool calls, {ep['test_runs']} test runs, "
        f"edited: {', '.join(ep['files_edited'][:12]) or 'nothing'}\n"
        f"AGENT FELL SHORT:\n{chr(10).join(short[:4]) or '(none labelled)'}\n"
        f"REVIEW BUGS:\n{chr(10).join(bugs[:4]) or '(none)'}\n"
    )


def usable(ep: dict) -> bool:
    """Pre-filter: a known commit, a real request, and some actual work."""
    return bool(ep.get("commit")) and len(ep["request"]) >= 80 and ep["tool_calls"] >= 3


#: Recent work per repo (user, 2026-11-18): harder and more representative than older
#: sessions. sd-scripts' actual rework started in October; the others changed in August.
RECENT_SINCE = {"sd-scripts": "2026-10-01"}
RECENT_DEFAULT = "2026-08-01"


def is_recent(ep: dict) -> bool:
    return (ep.get("start") or "") >= RECENT_SINCE.get(ep["repo"], RECENT_DEFAULT)


def sample(episodes: list[dict], *, per_big_repo: int = 200, seed: int = 23) -> list[dict]:
    """All usable episodes of small repos; for repos with more than ``per_big_repo``,
    half from episodes with trouble evidence (shortfall or review bug), half at random."""
    rng = random.Random(seed)
    by_repo: dict[str, list[dict]] = {}
    for ep in filter(usable, episodes):
        by_repo.setdefault(ep["repo"], []).append(ep)
    out = [e for e in filter(usable, episodes) if is_recent(e)]  # all recent work
    seen = {e["episode_id"] for e in out}
    by_repo = {k: [e for e in v if e["episode_id"] not in seen] for k, v in by_repo.items()}
    for eps in by_repo.values():
        if len(eps) <= per_big_repo:
            out += eps
            continue
        trouble = [e for e in eps if e.get("n_corrections") or e.get("review_bugs")]
        picked = rng.sample(trouble, min(per_big_repo // 2, len(trouble)))
        ids = {e["episode_id"] for e in picked}
        rest = [e for e in eps if e["episode_id"] not in ids]
        picked += rng.sample(rest, min(per_big_repo - len(picked), len(rest)))
        out += picked
    return out


def triage(
    candidates_jsonl: Path,
    cache_path: Path,
    *,
    per_big_repo: int = 200,
    parallel: int = 2,
    caller: Callable[[str], str] | None = None,
    log: Callable[[str], None] = print,
    backoff: float = 10.0,
) -> dict:
    if caller is None:

        def caller(user: str) -> str:
            return cl.call_glm(user, system=SYSTEM)

    episodes = [json.loads(x) for x in candidates_jsonl.read_text().splitlines() if x.strip()]
    chosen = sample(episodes, per_big_repo=per_big_repo)
    cache = cl.load_cache(cache_path)
    todo = [e for e in chosen if triage_key(e) not in cache]
    batches = [todo[i : i + BATCH] for i in range(0, len(todo), BATCH)]
    log(f"{len(chosen)} episodes sampled, {len(todo)} to triage in {len(batches)} calls")

    def fetch(i: int) -> list[dict] | None:
        for attempt in range(cl.RETRIES + 1):
            try:
                return cl.parse_labels(caller("\n".join(map(_render_one, batches[i]))))
            except (urllib.error.URLError, ValueError, TimeoutError, OSError) as err:
                log(f"triage batch {i + 1} attempt {attempt + 1} failed: {err}")
                if cl.is_quota_exhausted(err):
                    raise cl.QuotaExhausted(str(err)) from None
                time.sleep(cl.retry_delay(err, attempt, backoff))
        return None

    added = failures = consecutive = 0
    stopped = False
    width = max(1, parallel)
    with cache_path.open("a") as out, ThreadPoolExecutor(max_workers=width) as pool:
        for start in range(0, len(batches), width):
            wave = range(start, min(len(batches), start + width))
            try:
                results = list(pool.map(fetch, wave))
            except cl.QuotaExhausted as err:
                log(f"stopping: 5-hour window full, resume after it resets ({err})")
                stopped = True
                break
            for i, got in zip(wave, results, strict=True):
                if got is None:
                    failures += 1
                    consecutive += 1
                    continue
                consecutive = 0
                by_id = {str(x.get("id")): x for x in got if isinstance(x, dict)}
                for ep in batches[i]:
                    key = triage_key(ep)
                    g = by_id.get(key)
                    if not g or g.get("verdict") not in VERDICTS:
                        continue
                    rec = {
                        "key": key,
                        "episode_id": ep["episode_id"],
                        "repo": ep["repo"],
                        **{k: g.get(k) for k in ("task", "work_type", "size", "grading",
                                                 "gpu", "needs_history", "verdict", "why")},
                        "by": f"{cl.MODEL}/{PROMPT_VERSION}-{cl.THINKING_LEVEL}",
                    }  # fmt: skip
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    cache[key] = rec
                    added += 1
                out.flush()
                log(f"{time.strftime('%H:%M:%S')} triage batch {i + 1}/{len(batches)}")
            if consecutive >= cl.MAX_CONSECUTIVE_FAILURES:
                log(f"stopping: {consecutive} consecutive failed batches")
                stopped = True
                break
    done = [cache[triage_key(e)] for e in chosen if triage_key(e) in cache]
    return {
        "sampled": len(chosen),
        "triaged": len(done),
        "added": added,
        "failed_batches": failures,
        "stopped_early": stopped,
        "verdicts": dict(Counter(r["verdict"] for r in done)),
        "work_types": dict(Counter(r["work_type"] for r in done)),
    }
