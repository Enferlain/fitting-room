"""`fr mine`: sessions -> episodes -> redacted candidate files (spec: session-mining)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from fitting_room.miner.episodes import Episode, split_episodes
from fitting_room.miner.output import summarize, write_outputs
from fitting_room.miner.sessions import DEFAULT_SOURCES, iter_sessions

LABELS_FILE = "followup-labels.jsonl"


REVIEWS_FILE = "reviews.jsonl"
REVIEW_LABELS_FILE = "review-labels.jsonl"


def apply_review_bugs(episodes: list[Episode], out_dir: Path) -> int:
    """Attach GLM-confirmed review bugs to the episode they happened in: same session,
    review time at or after the episode start and before the next episode's start."""
    import json

    from fitting_room.miner.classify import load_cache
    from fitting_room.miner.review_labels import review_key

    reviews_path, labels_path = out_dir / REVIEWS_FILE, out_dir / REVIEW_LABELS_FILE
    if not reviews_path.exists() or not labels_path.exists():
        return 0
    labels = load_cache(labels_path)
    by_session: dict[tuple[str, str], list[Episode]] = {}
    for ep in episodes:
        by_session.setdefault((ep.source, ep.session_id), []).append(ep)
    attached = 0
    for line in reviews_path.read_text().splitlines():
        rev = json.loads(line)
        lab = labels.get(review_key(rev))
        if not lab or lab["label"] not in ("real_bug_fixed", "real_bug_unfixed"):
            continue
        eps = sorted(
            by_session.get((rev["source"], rev["session_id"]), []), key=lambda e: e.start or ""
        )
        target = None
        for ep in eps:
            if (ep.start or "") <= (rev["ts"] or ""):
                target = ep
        if target is None and eps:
            target = eps[0]
        if target is not None:
            target.review_bugs.append(
                {"review_id": rev["review_id"], "label": lab["label"], "bug": lab.get("bug", "")}
            )
            attached += 1
    return attached


def apply_labels(episodes: list[Episode], labels_path: Path) -> int:
    """Attach cached GLM follow-up labels (see miner.classify). Returns how many applied."""
    from fitting_room.miner.classify import cache_key, load_cache

    cache = load_cache(labels_path)
    applied = 0
    for ep in episodes:
        for fu in ep.follow_ups:
            rec = cache.get(cache_key(ep.episode_id, fu.ref, fu.text))
            if rec:
                fu.label, fu.label_reason = rec["label"], rec.get("reason")
                applied += 1
    return applied


def mine(
    repos: list[str],
    out_dir: Path,
    sources: dict[str, Path] | None = None,
) -> dict:
    """Mine episodes for sessions whose repo (git top-level name, else cwd name) is in
    ``repos`` (all repos if empty). Returns summary stats; writes files to ``out_dir``."""
    seen: Counter = Counter()
    skipped: Counter = Counter()
    episodes: list[Episode] = []
    for session in iter_sessions(sources or DEFAULT_SOURCES):
        seen[session.source] += 1
        if session.is_subagent:
            skipped["subagent"] += 1
            continue
        if not session.cwd:
            skipped["no_working_directory"] += 1
            continue
        if not session.human_messages:
            skipped["no_human_request"] += 1
            continue
        eps = split_episodes(session)
        if repos and (not eps or eps[0].repo not in repos):
            skipped["other_repo"] += 1
            continue
        episodes.extend(eps)
    stats = summarize(seen, skipped, episodes)
    stats["follow_ups_labelled"] = apply_labels(episodes, out_dir / LABELS_FILE)
    stats["review_bugs_attached"] = apply_review_bugs(episodes, out_dir)
    return write_outputs(episodes, stats, out_dir)
