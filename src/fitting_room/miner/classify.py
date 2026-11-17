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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from fitting_room.miner.episodes import _CONTINUATION

LABELS = ("agent_shortfall", "user_misunderstanding", "neutral", "unclear")
SHORTFALL_KINDS = (
    "wrong",  # wrong or broken change, false claim, violated instruction
    "missed",  # skipped part of the request or something it should have covered
    "shallow",  # vague or undetailed where depth was needed
    "no_context_check",  # asked or assumed instead of finding out from available context
    "sycophantic",  # agreed with / acted on the user's wrong premise or pushback
    "unwanted_action",  # did something not asked for (e.g. commit, scope creep)
    "communication",  # unclear explanation that made the user re-ask
    "other",
)
# Labels counted as "the agent fell short" by ranking and calibration (v1 + v2).
SHORTFALL_LABELS = ("model_error", "agent_shortfall")
ENDPOINT = "https://api.z.ai/api/coding/paas/v4/chat/completions"
PLACEHOLDER_KEY = "av-managed-key"  # Agent Vault substitutes the real key in-flight
CA_BUNDLE = "/etc/ssl/certs/ca-bundle.crt"
MODEL = "glm-5.3-flash"
BATCH = 8
PROMPT_VERSION = "followup-v3"
RETRIES = 2  # extra attempts per batch, with backoff
MAX_CONSECUTIVE_FAILURES = 5  # e.g. Agent Vault locked: stop instead of burning calls

SYSTEM = """You judge one exchange between a human and an AI coding agent: did the AGENT
fall short anywhere in it? For each item you get: the end of the agent's previous message
(BEFORE), the human's follow-up (FOLLOW-UP), the start of the agent's reply (AFTER), and
the agent's next tool calls (AGENT ACTIONS AFTER).

Judge on SUBSTANCE, using the context shown. Agents habitually say "you're right"
whether or not the human is right, so the agent's agreement, apology or concession is
NOT evidence of anything. Neither is the human's confidence: the human may lack context
too. Decide who was actually right.

Check both sides of the exchange:
- before: did the follow-up expose a shortfall in the agent's earlier message or work?
- after: was the agent's reply (and its actions) a shortfall in response to the follow-up?

Labels:
- agent_shortfall: on either side, the agent was wrong OR fell short of a competent
  colleague. Kinds: wrong (broken change, false claim, violated instruction), missed
  (skipped part of the request), shallow (vague or undetailed where depth was needed),
  no_context_check (asked or assumed instead of first finding out from the available
  context), sycophantic (agreed with or acted on the human's wrong premise, or changed
  correct work because the human pushed), unwanted_action (did something not asked for),
  communication (unclear explanation that made the human ask again), other. An initial
  error the agent fixes after the follow-up is still a shortfall (side "before").
- user_misunderstanding: the human was mistaken or confused, the agent's earlier answer
  was correct and adequate, and its reply handled it well (held position, explained).
- neutral: a new direction, extra requirement, genuine question, status check, or
  acknowledgement, and both the earlier message and the reply were adequate.
- unclear: the context shown is not enough to tell.

For agent_shortfall also give "kind" and "side": before, after, or both.
Answer with ONLY a JSON array:
[{"id": "<id>", "label": "<label>", "kind": "<kind or empty>", "side": "<side or empty>",
  "reason": "<= 25 words"}]."""


def cache_key(episode_id: str, ref: str, text: str) -> str:
    h = hashlib.sha256(f"{label_version()}\0{episode_id}\0{ref}\0{text}".encode()).hexdigest()
    return h[:24]


@dataclass
class Item:
    key: str
    episode_id: str
    ref: str
    text: str
    before: str
    after: str
    after_tools: list[str] = field(default_factory=list)


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
                    after_tools=fu.get("next_tools", []),
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
        return {"label": "neutral", "reason": "continuation phrase", "by": "rule"}
    return None


def _actions(tools: list[str]) -> str:
    return "\n".join(f"- {t}" for t in tools) if tools else "(none)"


def _render(items: list[Item]) -> str:
    parts = []
    for it in items:
        parts.append(
            f"### id: {it.key}\nBEFORE:\n{it.before or '(none)'}\n\n"
            f"FOLLOW-UP:\n{it.text[:2000]}\n\nAFTER:\n{it.after or '(none)'}\n\n"
            f"AGENT ACTIONS AFTER:\n{_actions(it.after_tools)}\n"
        )
    return "\n".join(parts)


class GLMHTTPError(OSError):
    """HTTP error from z.ai with its response body and Retry-After (seconds), if any."""

    def __init__(self, code: int, body: str, retry_after: float | None):
        self.code, self.body, self.retry_after = code, body, retry_after
        super().__init__(f"HTTP {code}: {body[:300]}")


class QuotaExhausted(Exception):
    """z.ai error 1308: the plan's 5-hour window is full; retrying before reset is useless."""


def is_quota_exhausted(err: Exception) -> bool:
    return isinstance(err, GLMHTTPError) and err.code == 429 and '"1308"' in err.body


def retry_delay(err: Exception, attempt: int, backoff: float) -> float:
    delay = backoff * (2**attempt)
    if isinstance(err, GLMHTTPError) and err.retry_after:
        delay = max(delay, err.retry_after)
    return delay


QUOTA_ENDPOINT = "https://api.z.ai/api/monitor/usage/quota/limit"
# Off by default: glm-5.3-flash labelling has not been seen to consume the plan's 5-hour
# token window; it is only *blocked* once the window is full (error 1308). Set a cap to
# pause labelling anyway when the window gets busy.
DEFAULT_QUOTA_CAP: int | None = None


def quota_percent(timeout: float = 30) -> int | None:
    """Current use of the plan's 5-hour token window in percent (None if unknown)."""
    req = urllib.request.Request(QUOTA_ENDPOINT, headers={"Authorization": PLACEHOLDER_KEY})
    ctx = ssl.create_default_context(cafile=CA_BUNDLE)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            data = json.load(r)
    except (OSError, ValueError):
        return None
    for lim in (data.get("data") or {}).get("limits") or []:
        if lim.get("type") == "TOKENS_LIMIT":
            return int(lim.get("percentage") or 0)
    return None


def _quota_percent() -> Callable[[], int | None]:
    """Resolve the quota checker at call time (tests replace ``quota_percent``)."""
    import fitting_room.miner.classify as mod

    return mod.quota_percent


def quota_exceeded(cap: int | None, check: Callable[[], int | None] = quota_percent) -> int | None:
    """Return the current percentage if it is at or above ``cap``, else None."""
    if cap is None:
        return None
    pct = check()
    return pct if pct is not None and pct >= cap else None


ANTHROPIC_ENDPOINT = "https://api.z.ai/api/anthropic/v1/messages"
# Thinking budget per call, as Oh My Pi sends it to z.ai for its thinking levels:
# minimal 1024, low 2048, medium 8192, high 16384, xhigh/max 32768.
THINKING_BUDGETS = {"low": 2048, "medium": 8192, "high": 16384, "max": 32768}
THINKING_LEVEL = "max"


def set_thinking_level(level: str) -> None:
    global THINKING_LEVEL
    if level not in THINKING_BUDGETS:
        raise ValueError(f"thinking level must be one of {list(THINKING_BUDGETS)}")
    THINKING_LEVEL = level


def label_version() -> str:
    """Prompt version plus thinking level: different levels never share cached labels."""
    return f"{PROMPT_VERSION}-{THINKING_LEVEL}"


def call_glm(user: str, *, system: str = SYSTEM, timeout: float = 600) -> str:
    """One GLM call with explicit thinking budget, via z.ai's Anthropic-compatible API
    (the same request shape Oh My Pi uses for its thinking levels)."""
    budget = THINKING_BUDGETS[THINKING_LEVEL]
    body = {
        "model": MODEL,
        "max_tokens": budget + 8000,
        "thinking": {"type": "enabled", "budget_tokens": budget},
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        ANTHROPIC_ENDPOINT,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {PLACEHOLDER_KEY}",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    ctx = ssl.create_default_context(cafile=CA_BUNDLE)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        ra = e.headers.get("retry-after")
        raise GLMHTTPError(e.code, body_text, float(ra) if ra and ra.isdigit() else None) from None
    return "".join(c.get("text", "") for c in data.get("content", []) if c.get("type") == "text")


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
    only_keys: set[str] | None = None,
    caller: Callable[[str], str] = call_glm,
    log: Callable[[str], None] = print,
    backoff: float = 10.0,
    parallel: int = 1,
    quota_cap: int | None = DEFAULT_QUOTA_CAP,
    quota_check: Callable[[], int | None] | None = None,
) -> dict:
    """Label follow-ups not yet in the cache. Returns counts."""
    cache = load_cache(cache_path)
    todo: list[Item] = []
    added_local = 0
    with cache_path.open("a") as out:
        for it in iter_items(candidates_jsonl):
            if it.key in cache or (episode_filter and not episode_filter(it.episode_id)):
                continue
            if only_keys is not None and it.key not in only_keys:
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
        calls = failures = added_model = consecutive = 0
        stopped = False
        n_batches = (len(todo) + BATCH - 1) // BATCH
        batches = [todo[i : i + BATCH] for i in range(0, len(todo), BATCH)]

        def fetch(index: int) -> list[dict] | None:
            for attempt in range(RETRIES + 1):
                try:
                    return parse_labels(caller(_render(batches[index])))
                except (urllib.error.URLError, ValueError, TimeoutError, OSError) as err:
                    log(f"batch {index + 1} attempt {attempt + 1} failed: {err}")
                    if is_quota_exhausted(err):
                        raise QuotaExhausted(str(err)) from None
                    time.sleep(retry_delay(err, attempt, backoff))
            return None

        # Waves of `parallel` concurrent calls; results are written from this thread only.
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            for wave_start in range(0, n_batches, max(1, parallel)):
                if (pct := quota_exceeded(quota_cap, quota_check or _quota_percent())) is not None:
                    log(f"stopping: 5-hour quota at {pct}% (cap {quota_cap}%)")
                    stopped = True
                    break
                wave = range(wave_start, min(n_batches, wave_start + max(1, parallel)))
                try:
                    results = list(pool.map(fetch, wave))
                except QuotaExhausted as err:
                    log(f"stopping: 5-hour window full, resume after it resets ({err})")
                    stopped = True
                    break
                for index, labels in zip(wave, results, strict=True):
                    if labels is None:
                        failures += 1
                        consecutive += 1
                        continue
                    consecutive = 0
                    calls += 1
                    by_id = {str(x.get("id")): x for x in labels if isinstance(x, dict)}
                    for it in batches[index]:
                        got = by_id.get(it.key)
                        if not got or got.get("label") not in LABELS:
                            continue
                        rec = {
                            "key": it.key,
                            "episode_id": it.episode_id,
                            "ref": it.ref,
                            "label": got["label"],
                            "reason": str(got.get("reason", ""))[:300],
                            "kind": str(got.get("kind") or "")[:40],
                            "side": str(got.get("side") or "")[:10],
                            "by": f"{MODEL}/{label_version()}",
                        }
                        out.write(json.dumps(rec) + "\n")
                        cache[it.key] = rec
                        added_model += 1
                    out.flush()
                    log(
                        f"{time.strftime('%H:%M:%S')} batch {index + 1}/{n_batches}: "
                        f"{len(by_id)} labels"
                    )
                if consecutive >= MAX_CONSECUTIVE_FAILURES:
                    log(f"stopping: {consecutive} consecutive failed batches")
                    stopped = True
                    break
    return {
        "labelled_by_rule": added_local,
        "labelled_by_model": added_model,
        "model_calls": calls,
        "failed_batches": failures,
        "stopped_early": stopped,
        "cached_total": len(cache),
    }
