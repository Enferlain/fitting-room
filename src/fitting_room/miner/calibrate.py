"""Blind human check of GLM follow-up labels (calibration for fitting-room-kap.2).

The only distinction the candidate ranking relies on is "was the model actually wrong?",
so the human answers yes / no / unclear per item, without seeing GLM's label (to avoid
anchoring). GLM's labels are kept in a separate key file and compared afterwards.

Sample: weighted toward the labels that matter (default 20 model_error,
15 misunderstanding, 15 from the rest), drawn with a fixed seed.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from fitting_room.miner.classify import iter_items, load_cache
from fitting_room.miner.output import redact

ANSWERS = ("yes", "no", "unclear")
_ITEM = re.compile(r"^## Item (\d+)\s*$", re.M)
_ANSWER = re.compile(r"^\*\*(?:Model wrong|Agent fell short)\?\*\*.*?:\s*(\S*)\s*$", re.M)


def _quote(text: str) -> str:
    text = text.strip() or "(none)"
    return "\n".join("> " + line for line in text.splitlines())


def write_sample(
    candidates_jsonl: Path,
    labels_jsonl: Path,
    out_dir: Path,
    *,
    n_error: int = 20,
    n_misunderstanding: int = 15,
    n_other: int = 15,
    seed: int = 17,
) -> dict:
    cache = load_cache(labels_jsonl)
    items = [it for it in iter_items(candidates_jsonl) if it.key in cache]
    by_group: dict[str, list] = {"model_error": [], "misunderstanding": [], "other": []}
    for it in items:
        label = cache[it.key]["label"]
        if cache[it.key].get("by") == "rule":
            continue  # rule-labelled acknowledgements are not what we are checking
        by_group[label if label in by_group else "other"].append(it)
    rng = random.Random(seed)
    want = {"model_error": n_error, "misunderstanding": n_misunderstanding, "other": n_other}
    chosen = []
    for group, n in want.items():
        pool = by_group[group]
        chosen += rng.sample(pool, min(n, len(pool)))
    rng.shuffle(chosen)

    lines = [
        "# Calibration check: did the agent fall short in this exchange?",
        "",
        "For each item, read the agent's message BEFORE, your FOLLOW-UP and the agent's",
        "reply AFTER. Did the agent fall short anywhere: in its earlier message, or in its",
        "reply? Replace the blank after **Agent fell short?** with `yes`, `no` or `unclear`.",
        "",
        "- `yes`: the agent was wrong or fell short: wrong or broken change, ignored an",
        "  instruction, false claim, unwanted action, missed part of the request, shallow",
        "  answer, asked/assumed instead of checking context, agreed with you when you",
        "  were wrong.",
        "- `no`: the agent was fine: you were asking, changing direction, or had",
        "  misunderstood something yourself.",
        "- `unclear`: can't tell from this context.",
        "",
        "GLM's labels are in `key.jsonl`; don't open it until you're done.",
        "Then run `uv run fr calibrate score`.",
        "",
    ]
    key = []
    for n, it in enumerate(chosen, start=1):
        lines += [
            f"## Item {n}",
            "",
            f"`{it.episode_id}` {it.ref}",
            "",
            "**BEFORE** (end of the agent's message):",
            "",
            _quote(it.before),
            "",
            "**FOLLOW-UP** (you):",
            "",
            _quote(it.text[:2000]),
            "",
            "**AFTER** (start of the agent's reply):",
            "",
            _quote(it.after),
            "",
            "**Agent fell short?** (yes / no / unclear): ",
            "",
        ]
        rec = cache[it.key]
        key.append({"item": n, "key": it.key, "label": rec["label"], "reason": rec.get("reason")})
    out_dir.mkdir(parents=True, exist_ok=True)
    check = out_dir / "check.md"
    if check.exists():
        raise FileExistsError(f"{check} exists; move it away to draw a new sample")
    red = redact("\n".join(lines))
    check.write_text(red.text)
    (out_dir / "key.jsonl").write_text("".join(json.dumps(k) + "\n" for k in key))
    return {"items": len(chosen), "available": {g: len(v) for g, v in by_group.items()}}


@dataclass
class Score:
    answered: int
    unclear: int
    unanswered: int
    model_error_precision: float | None  # of GLM's model_error, share the human said yes
    missed_errors: int  # human yes, GLM said something else
    agreement: float | None  # binary: model_error vs not, unclear excluded
    kappa: float | None
    disagreements: list[dict]


def _kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    pa = sum(a for a, _ in pairs) / n
    pb = sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe == 1 else (po - pe) / (1 - pe)


def read_answers(check_md: Path) -> dict[int, str]:
    text = check_md.read_text()
    answers = {}
    parts = _ITEM.split(text)
    # parts: [preamble, n1, body1, n2, body2, ...]
    for n, body in zip(parts[1::2], parts[2::2], strict=True):
        m = _ANSWER.search(body)
        answers[int(n)] = (m.group(1).strip("`*").lower() if m else "") or ""
    return answers


_ITEM_REF = re.compile(r"^`([^`]+)` (\S+)\s*$", re.M)


def item_refs(check_md: Path) -> dict[int, tuple[str, str]]:
    """Item number -> (episode_id, ref), as printed under each item heading."""
    parts = _ITEM.split(check_md.read_text())
    out = {}
    for n, body in zip(parts[1::2], parts[2::2], strict=True):
        if m := _ITEM_REF.search(body):
            out[int(n)] = (m.group(1), m.group(2))
    return out


def relabel_key(out_dir: Path, candidates_jsonl: Path, labels_jsonl: Path) -> dict[int, dict]:
    """Key for scoring against the *current* prompt version's labels of the same items."""
    from fitting_room.miner.classify import iter_items, load_cache

    cache = load_cache(labels_jsonl)
    by_ref = {(it.episode_id, it.ref): it.key for it in iter_items(candidates_jsonl)}
    out = {}
    for n, ref in item_refs(out_dir / "check.md").items():
        rec = cache.get(by_ref.get(ref, ""))
        if rec:
            out[n] = {
                "item": n,
                "label": rec["label"],
                "reason": rec.get("reason"),
                "kind": rec.get("kind"),
            }
    return out


def score(out_dir: Path, key_override: dict[int, dict] | None = None) -> Score:
    from fitting_room.miner.classify import SHORTFALL_LABELS

    answers = read_answers(out_dir / "check.md")
    key = key_override or {
        k["item"]: k for k in map(json.loads, (out_dir / "key.jsonl").read_text().splitlines())
    }
    pairs: list[tuple[bool, bool]] = []  # (human_wrong, glm_wrong)
    unclear = unanswered = missed = 0
    disagreements = []
    for item, k in sorted(key.items()):
        if key_override is not None and item not in key_override:
            continue
        ans = answers.get(item, "")
        if ans not in ANSWERS:
            unanswered += 1
            continue
        if ans == "unclear":
            unclear += 1
            continue
        human, glm = ans == "yes", k["label"] in SHORTFALL_LABELS
        pairs.append((human, glm))
        if human and not glm:
            missed += 1
        if human != glm:
            disagreements.append({"item": item, "you": ans, "glm": k["label"], "why": k["reason"]})
    glm_err = [h for h, g in pairs if g]
    return Score(
        answered=len(pairs) + unclear,
        unclear=unclear,
        unanswered=unanswered,
        model_error_precision=(sum(glm_err) / len(glm_err)) if glm_err else None,
        missed_errors=missed,
        agreement=(sum(h == g for h, g in pairs) / len(pairs)) if pairs else None,
        kappa=_kappa(pairs),
        disagreements=disagreements,
    )
