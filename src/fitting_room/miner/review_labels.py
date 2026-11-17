"""Label extracted reviews with GLM: did the review find a real bug? (fitting-room-kap.3)

Input per review: what was reviewed, the review report, the agent's next reply and the
files it edited / tests it ran afterwards. GLM 5.3 Flash, thinking on, via Agent Vault;
cached by content hash; parallel waves with retries and a consecutive-failure stop.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fitting_room.miner.classify import (
    MAX_CONSECUTIVE_FAILURES,
    MODEL,
    RETRIES,
    call_glm,
    load_cache,
    parse_labels,
    retry_delay,
)

LABELS = ("real_bug_fixed", "real_bug_unfixed", "false_positive", "minor_only", "no_findings")
PROMPT_VERSION = "review-v1"
BATCH = 3

SYSTEM = """You judge code reviews of an AI coding agent's work.
For each item you get: what was reviewed (REQUEST), the review (REPORT), the agent's
next reply (AGENT REPLY), and the files it edited and tests it ran right after (FOLLOW-UP).

Pick exactly one label:
- real_bug_fixed: the review found at least one real defect (wrong behaviour, broken
  logic, missing required handling, failing or missing test for real behaviour,
  violated requirement) AND the agent accepted it and fixed it (reply and/or edits).
- real_bug_unfixed: a real defect was found and the agent agreed, but did not fix it
  in what follows (deferred, filed, or left).
- false_positive: the review claimed defects, but the agent checked and rejected them
  with a sound reason (or the claims are evidently wrong).
- minor_only: only style, naming, docs, wording or optional suggestions.
- no_findings: the review found nothing to change.

Do not count style nits as real defects. Judge from the evidence given.
For real_bug_fixed / real_bug_unfixed also give "bug": one line describing the defect.
Answer with ONLY a JSON array:
[{"id": "<id>", "label": "<label>", "bug": "<one line or empty>", "reason": "<= 25 words"}]."""


def review_key(rec: dict) -> str:
    raw = f"{PROMPT_VERSION}\0{rec['review_id']}\0{rec['report'][:2000]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _render(recs: list[dict]) -> str:
    parts = []
    for r in recs:
        follow = (
            f"edited: {', '.join(r['edits_after'][:12]) or 'nothing'}; "
            f"test runs: {r['tests_after']}"
        )
        parts.append(
            f"### id: {review_key(r)}\nREQUEST:\n{r['request'][:800]}\n\n"
            f"REPORT:\n{r['report'][:4000]}\n\n"
            f"AGENT REPLY:\n{r['next_assistant'][:1500] or '(none)'}"
            f"\n\nFOLLOW-UP:\n{follow}\n"
        )
    return "\n".join(parts)


def label_reviews(
    reviews_jsonl: Path,
    cache_path: Path,
    *,
    limit: int | None = None,
    parallel: int = 1,
    caller: Callable[[str], str] | None = None,
    log: Callable[[str], None] = print,
    backoff: float = 10.0,
) -> dict:
    if caller is None:

        def caller(user: str) -> str:
            return call_glm(user, system=SYSTEM)

    cache = load_cache(cache_path)
    recs = [json.loads(x) for x in reviews_jsonl.read_text().splitlines() if x.strip()]
    todo = [r for r in recs if review_key(r) not in cache]
    if limit is not None:
        todo = todo[:limit]
    batches = [todo[i : i + BATCH] for i in range(0, len(todo), BATCH)]

    def fetch(index: int) -> list[dict] | None:
        for attempt in range(RETRIES + 1):
            try:
                return parse_labels(caller(_render(batches[index])))
            except (urllib.error.URLError, ValueError, TimeoutError, OSError) as err:
                log(f"review batch {index + 1} attempt {attempt + 1} failed: {err}")
                time.sleep(retry_delay(err, attempt, backoff))
        return None

    calls = failures = added = consecutive = 0
    stopped = False
    width = max(1, parallel)
    with cache_path.open("a") as out, ThreadPoolExecutor(max_workers=width) as pool:
        for start in range(0, len(batches), width):
            wave = range(start, min(len(batches), start + width))
            for index, labels in zip(wave, pool.map(fetch, wave), strict=True):
                if labels is None:
                    failures += 1
                    consecutive += 1
                    continue
                consecutive = 0
                calls += 1
                by_id = {str(x.get("id")): x for x in labels if isinstance(x, dict)}
                for r in batches[index]:
                    key = review_key(r)
                    got = by_id.get(key)
                    if not got or got.get("label") not in LABELS:
                        continue
                    rec = {
                        "key": key,
                        "review_id": r["review_id"],
                        "label": got["label"],
                        "bug": str(got.get("bug") or "")[:300],
                        "reason": str(got.get("reason") or "")[:300],
                        "by": f"{MODEL}/{PROMPT_VERSION}",
                    }
                    out.write(json.dumps(rec) + "\n")
                    cache[key] = rec
                    added += 1
                out.flush()
                log(f"{time.strftime('%H:%M:%S')} review batch {index + 1}/{len(batches)}")
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                log(f"stopping: {consecutive} consecutive failed batches")
                stopped = True
                break
    return {
        "labelled": added,
        "model_calls": calls,
        "failed_batches": failures,
        "stopped_early": stopped,
        "cached_total": len(cache),
    }
