"""`fr mine`: sessions -> episodes -> redacted candidate files (spec: session-mining)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from fitting_room.miner.episodes import Episode, split_episodes
from fitting_room.miner.output import summarize, write_outputs
from fitting_room.miner.sessions import DEFAULT_SOURCES, iter_sessions


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
    return write_outputs(episodes, summarize(seen, skipped, episodes), out_dir)
