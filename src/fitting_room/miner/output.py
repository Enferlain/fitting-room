"""Write reviewable candidate files with secrets redacted (spec: session-mining).

Content is assembled in memory, scanned for secrets, redacted, and only then written.
gitleaks is the primary scanner. When it is missing, a regex fallback is used and a
warning is returned. Output stays under ``work/`` (gitignored).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from fitting_room.miner.episodes import Episode

REDACTED = "[REDACTED]"

_FALLBACK_PATTERNS = [
    re.compile(p)
    for p in (
        r"sk-[A-Za-z0-9_\-]{20,}",
        r"sk-ant-[A-Za-z0-9_\-]{20,}",
        r"gh[pousr]_[A-Za-z0-9]{30,}",
        r"github_pat_[A-Za-z0-9_]{30,}",
        r"AKIA[0-9A-Z]{16}",
        r"xox[abprs]-[A-Za-z0-9\-]{10,}",
        r"AIza[0-9A-Za-z_\-]{35}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----",
        r"(?i)(?:api[_-]?key|secret|token|password)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+]{16,}",
    )
]


@dataclass
class RedactionResult:
    text: str
    count: int
    scanner: str
    warning: str | None = None


def _gitleaks_secrets(text: str) -> list[str] | None:
    exe = shutil.which("gitleaks")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "scan" / "candidates.txt"
        src.parent.mkdir()
        src.write_text(text)
        report = Path(tmp) / "report.json"
        subprocess.run(
            [exe, "dir", str(src.parent), "--no-banner", "--report-format", "json",
             "--report-path", str(report), "--exit-code", "0"],
            capture_output=True,
            text=True,
        )  # fmt: skip
        if not report.exists():
            return None
        findings = json.loads(report.read_text() or "[]")
    return sorted({f["Secret"] for f in findings if f.get("Secret")}, key=len, reverse=True)


def redact(text: str) -> RedactionResult:
    secrets = _gitleaks_secrets(text)
    if secrets is not None:
        count = 0
        for s in secrets:
            count += text.count(s)
            text = text.replace(s, REDACTED)
        # gitleaks misses some formats the fallback knows; apply both.
        for pat in _FALLBACK_PATTERNS:
            text, n = pat.subn(REDACTED, text)
            count += n
        return RedactionResult(text, count, "gitleaks+regex")
    count = 0
    for pat in _FALLBACK_PATTERNS:
        text, n = pat.subn(REDACTED, text)
        count += n
    return RedactionResult(text, count, "regex", "gitleaks not found; used regex fallback only")


TOP_PER_REPO = 40


def review_score(ep: Episode) -> float:
    """Rough priority for review: corrections and verifiable work rank first.
    Corrections reveal failure modes; edits plus tests suggest a checkable coding task;
    many tool calls without edits suggest a real exploration task."""
    score = 3.0 * min(len(ep.corrections), 3)
    # A review that found a real bug is the strongest evidence of a model error.
    score += 4.0 * min(sum(b["label"] == "real_bug_fixed" for b in ep.review_bugs), 2)
    score += 2.0 * min(sum(b["label"] == "real_bug_unfixed" for b in ep.review_bugs), 2)
    score += 2.0 if ep.files_edited else 0.0
    score += 1.0 if ep.test_runs else 0.0
    score += min(ep.tool_calls, 40) / 20
    if not ep.commit:
        score -= 2.0  # repo state not recoverable: hard to turn into a task
    return round(score, 2)


def _one_line(text: str, limit: int = 140) -> str:
    t = " ".join(text.split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _bugs_cell(ep: Episode) -> str:
    fixed = [b for b in ep.review_bugs if b["label"] == "real_bug_fixed"]
    unfixed = [b for b in ep.review_bugs if b["label"] == "real_bug_unfixed"]
    if not fixed and not unfixed:
        return ""
    first = (fixed or unfixed)[0].get("bug") or ""
    return f"{len(fixed)} fixed, {len(unfixed)} unfixed: {_one_line(first, 70)}"


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown(episodes: list[Episode], stats: dict, top: int | None = TOP_PER_REPO) -> str:
    title = "Mined task candidates" + (f" (top {top} per repo)" if top else " (all)")
    lines = [f"# {title}", ""]
    lines.append(
        "Review these and pick candidates for task authoring (checkpoint 1). "
        "Full records are in `candidates.jsonl`; every row is in `candidates-all.md`. "
        "Rows are ranked by a rough review score; heuristic fields are suggestions only."
    )
    lines += ["", "## Summary", ""]
    for key in ("sessions_by_source", "skipped", "episodes_by_repo", "episodes_by_track"):
        lines.append(f"- **{key.replace('_', ' ')}:** " + ", ".join(
            f"{k}: {v}" for k, v in sorted(stats.get(key, {}).items())
        ))  # fmt: skip
    lines.append(f"- **secrets redacted:** {stats.get('redacted', 0)} ({stats.get('scanner')})")
    by_repo: dict[str, list[Episode]] = {}
    for ep in episodes:
        by_repo.setdefault(ep.repo or "?", []).append(ep)
    for repo, eps in sorted(by_repo.items()):
        lines += ["", f"## {repo} ({len(eps)})", ""]
        lines.append(
            "| score | episode | start | commit | track | edits | tests | corrections "
            "| review bugs | request |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        ranked = sorted(eps, key=lambda e: (-review_score(e), e.start or ""))
        for ep in ranked[:top] if top else ranked:
            commit = (ep.commit or "unknown")[:10] + ("*" if ep.commit_inferred else "")
            lines.append(
                f"| {review_score(ep)} | `{ep.episode_id}` {ep.request_ref} | "
                f"{(ep.start or '')[:16]} | {commit} | "
                f"{ep.suggested_track} | {len(ep.files_edited)} | {ep.test_runs} | "
                f"{len(ep.corrections)} | {_md_cell(_bugs_cell(ep))} | "
                f"{_md_cell(_one_line(ep.request))} |"
            )
    lines += ["", "`*` = commit inferred from the repo's history at the episode's start time.", ""]
    return "\n".join(lines)


def write_outputs(episodes: list[Episode], stats: dict, out_dir: Path) -> dict:
    """Redact, then write candidates.md and candidates.jsonl. Returns updated stats."""
    jsonl = "".join(
        json.dumps({**ep.to_dict(), "review_score": review_score(ep)}, ensure_ascii=False) + "\n"
        for ep in episodes
    )
    red_jsonl = redact(jsonl)
    stats = {**stats, "redacted": red_jsonl.count, "scanner": red_jsonl.scanner}
    red_md = redact(render_markdown(episodes, stats))
    red_all = redact(render_markdown(episodes, stats, top=None))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates.jsonl").write_text(red_jsonl.text)
    (out_dir / "candidates.md").write_text(red_md.text)
    (out_dir / "candidates-all.md").write_text(red_all.text)
    if red_jsonl.warning:
        stats["warning"] = red_jsonl.warning
    return stats


def summarize(sessions_seen: Counter, skipped: Counter, episodes: list[Episode]) -> dict:
    return {
        "sessions_by_source": dict(sessions_seen),
        "skipped": dict(skipped),
        "episodes_by_repo": dict(Counter(e.repo or "?" for e in episodes)),
        "episodes_by_track": dict(Counter(e.suggested_track for e in episodes)),
    }
