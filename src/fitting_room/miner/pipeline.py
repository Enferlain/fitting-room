"""`fr mine`: sessions -> episodes -> redacted candidate files (spec: session-mining)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from fitting_room.miner.episodes import Episode, split_episodes
from fitting_room.miner.output import summarize, write_outputs
from fitting_room.miner.sessions import DEFAULT_SOURCES, iter_sessions

LABELS_FILE = "followup-labels.jsonl"


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
    return write_outputs(episodes, stats, out_dir)
