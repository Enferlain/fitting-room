"""Classify episode follow-ups with GLM (beads fitting-room-kap.2).

Keyword "pushback" is a weak signal: sometimes the human was the one who misunderstood.
What matters for task authoring is whether the *model* was wrong, so each follow-up is
classified with the assistant message before and after it as context:

- model_error: the human points out a real mistake by the model;
- misunderstanding: the human misread or was confused, the model's answer was fine;
- scope_change: new direction or requirement, not a fix;
- question: asks for explanation or status;
- acknowledgement: ok / continue / thanks.

GLM is called through the host's Agent Vault with a placeholder key, always with
thinking enabled. Labels are cached by content hash, so re-runs never repeat a call.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from fitting_room.miner.episodes import _CONTINUATION

LABELS = ("model_error", "misunderstanding", "scope_change", "question", "acknowledgement")
ENDPOINT = "https://api.z.ai/api/coding/paas/v4/chat/completions"
PLACEHOLDER_KEY = "av-managed-key"  # Agent Vault substitutes the real key in-flight
CA_BUNDLE = "/etc/ssl/certs/ca-bundle.crt"
MODEL = "glm-5.3-flash"
BATCH = 8
PROMPT_VERSION = "followup-v1"

SYSTEM = """You label a human's follow-up messages to an AI coding agent.
For each item you get: the end of the agent's previous message (BEFORE), the human's
follow-up (FOLLOW-UP), and the start of the agent's next reply (AFTER).

Pick exactly one label:
- model_error: the follow-up points out a real mistake by the agent: wrong or broken
  change, ignored or violated an instruction, false claim, unwanted action (e.g. an
  unrequested commit), or missed something it was asked to do. Use AFTER as evidence:
  the agent conceding or fixing supports this.
- misunderstanding: the human pushes back or is confused, but the agent's earlier
  answer was reasonable; AFTER explains or clarifies rather than fixing. Also use this
  when the human admits their own mistake.
- scope_change: a new direction, extra requirement, or change of plan, not a fix.
- question: asks for explanation, status, or opinion without implying a mistake.
- acknowledgement: approval, "continue", thanks, or similar.

If it is truly ambiguous, choose the most likely label and say why briefly.
Answer with ONLY a JSON array: [{"id": "<id>", "label": "<label>", "reason": "<= 20 words"}]."""


def cache_key(episode_id: str, ref: str, text: str) -> str:
    h = hashlib.sha256(f"{PROMPT_VERSION}\0{episode_id}\0{ref}\0{text}".encode()).hexdigest()
    return h[:24]


@dataclass
class Item:
    key: str
    episode_id: str
    ref: str
    text: str
    before: str
    after: str


def iter_items(candidates_jsonl: Path) -> Iterator[Item]:
    with candidates_jsonl.open() as fh:
        for line in fh:
            ep = json.loads(line)
            for fu in ep["follow_ups"]:
                yield Item(
                    key=cache_key(ep["episode_id"], fu["ref"], fu["text"]),
                    episode_id=ep["episode_id"],
                    ref=fu["ref"],
                    text=fu["text"],
                    before=fu.get("prev_assistant", ""),
                    after=fu.get("next_assistant", ""),
                )


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["key"]] = rec
    return out


def local_label(item: Item) -> dict | None:
    """Label obvious acknowledgements without a model call."""
    if _CONTINUATION.match(item.text.strip()):
        return {"label": "acknowledgement", "reason": "continuation phrase", "by": "rule"}
    return None


def _render(items: list[Item]) -> str:
    parts = []
    for it in items:
        parts.append(
            f"### id: {it.key}\nBEFORE:\n{it.before or '(none)'}\n\n"
            f"FOLLOW-UP:\n{it.text[:2000]}\n\nAFTER:\n{it.after or '(none)'}\n"
        )
    return "\n".join(parts)


def call_glm(user: str, *, timeout: float = 300) -> str:
    body = {
        "model": MODEL,
        "max_tokens": 16000,  # thinking stays enabled (user rule); leave room for it
        "thinking": {"type": "enabled"},
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {PLACEHOLDER_KEY}",
            "content-type": "application/json",
        },
    )
    ctx = ssl.create_default_context(cafile=CA_BUNDLE)
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
        data = json.load(r)
    return data["choices"][0]["message"].get("content") or ""


def parse_labels(text: str) -> list[dict]:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError(f"no JSON array in reply: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def classify(
    candidates_jsonl: Path,
    cache_path: Path,
    *,
    limit: int | None = None,
    episode_filter: Callable[[str], bool] | None = None,
    caller: Callable[[str], str] = call_glm,
    log: Callable[[str], None] = print,
) -> dict:
    """Label follow-ups not yet in the cache. Returns counts."""
    cache = load_cache(cache_path)
    todo: list[Item] = []
    added_local = 0
    with cache_path.open("a") as out:
        for it in iter_items(candidates_jsonl):
            if it.key in cache or (episode_filter and not episode_filter(it.episode_id)):
                continue
            if (lab := local_label(it)) is not None:
                rec = {"key": it.key, "episode_id": it.episode_id, "ref": it.ref, **lab}
                out.write(json.dumps(rec) + "\n")
                cache[it.key] = rec
                added_local += 1
                continue
            todo.append(it)
            if limit is not None and len(todo) >= limit:
                break
        calls = failures = added_model = 0
        for i in range(0, len(todo), BATCH):
            batch = todo[i : i + BATCH]
            try:
                labels = parse_labels(caller(_render(batch)))
            except (urllib.error.URLError, ValueError, TimeoutError) as err:
                failures += 1
                log(f"batch {i // BATCH} failed: {err}")
                time.sleep(2)
                continue
            calls += 1
            by_id = {str(x.get("id")): x for x in labels if isinstance(x, dict)}
            for it in batch:
                got = by_id.get(it.key)
                if not got or got.get("label") not in LABELS:
                    continue
                rec = {
                    "key": it.key,
                    "episode_id": it.episode_id,
                    "ref": it.ref,
                    "label": got["label"],
                    "reason": str(got.get("reason", ""))[:300],
                    "by": f"{MODEL}/{PROMPT_VERSION}",
                }
                out.write(json.dumps(rec) + "\n")
                out.flush()
                cache[it.key] = rec
                added_model += 1
            log(f"batch {i // BATCH + 1}/{(len(todo) + BATCH - 1) // BATCH}: {len(by_id)} labels")
    return {
        "labelled_by_rule": added_local,
        "labelled_by_model": added_model,
        "model_calls": calls,
        "failed_batches": failures,
        "cached_total": len(cache),
    }
