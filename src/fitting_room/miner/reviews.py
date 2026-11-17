"""Extract review passes from session histories (beads fitting-room-kap.3).

A review that found a real bug, followed by a fix, is a confirmed model error with a
reference solution. This module only *extracts* reviews with what happened next; a
later GLM pass labels whether the findings were real (fixed) or false positives.

Sources:
- Codex: review-mcp ``review_with_context`` called directly (function_call_output is
  ``{"result": markdown}``) or inside code-mode ``exec`` (output in chunks).
- Claude Code: Agent/Task tool calls whose description mentions review / audit /
  verify. Background agents return "launched"; their report arrives later as a queued
  ``<agent-message from="<id>"> [Subagent hand-back]`` record.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fitting_room.miner.episodes import _PATCH_FILE, repo_root_of

REVIEW_WORDS = re.compile(r"\b(review|audit|verif|adversarial|critique)", re.I)
_AGENT_ID = re.compile(r"agentId:\s*([0-9a-f]{8,})")
_CELL_RUNNING = re.compile(r"Script running with cell ID (\d+)")
# Foreground agents that hand back via a message instead of the tool result.
_DELIVERED_AS_MESSAGE = re.compile(r'delivered to you as a message from "([0-9a-f]{8,})"')
_HANDBACK = re.compile(r'<agent-message from="([0-9a-f]+)">\s*(.*)', re.S)
FOLLOW_TOOL_CALLS = 15  # tool calls after the report to scan for fixes
_FAILED = re.compile(
    r"tool call (error|failed)|timed out awaiting|Error calling model|Usage limit reached|"
    r"\b429\b|rate limit|Could not create saved review|review timed out|"
    r'"result"\s*:\s*"Error\b|^\s*Error\b',
    re.I,
)
_HANDBACK_PREAMBLE = re.compile(r"^\[Subagent hand-back\].*?(?:\n\s*\n|$)", re.S)
_EDIT_TOOL_NAMES = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
TEXT_LIMIT = 6000


@dataclass
class Review:
    source: str
    session_id: str
    session_path: str
    repo: str | None
    ref: str
    ts: str | None
    kind: str  # review-mcp | claude-agent
    request: str  # what was asked to be reviewed
    report: str = ""
    next_assistant: str = ""
    edits_after: list[str] = field(default_factory=list)
    tests_after: int = 0
    failed: bool = False  # the review itself errored (timeout, quota, tool failure)

    @property
    def review_id(self) -> str:
        return f"{self.source}:{self.session_id}@{self.ref}"

    def finish(self, report: str) -> None:
        report = _HANDBACK_PREAMBLE.sub("", report.lstrip(), count=1).strip()
        self.report = report[:TEXT_LIMIT]
        self.failed = len(report) < 600 and bool(_FAILED.search(report))

    def to_dict(self) -> dict:
        return {**asdict(self), "review_id": self.review_id}


def _rows(path: Path) -> Iterator[tuple[int, dict]]:
    with path.open(encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, start=1):
            try:
                yield n, json.loads(line)
            except json.JSONDecodeError:
                continue


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            c.get("text", "") if isinstance(c, dict) else str(c) for c in content
        ).strip()
    return ""


def _repo(cwd: str | None) -> str | None:
    root = repo_root_of(cwd)
    return Path(root).name if root else (Path(cwd).name if cwd else None)


def _track_after(review: Review, events: list[tuple[str, str]]) -> None:
    """events: ("assistant", text) / ("tool", args) after the report, in order."""
    tools = 0
    for kind, payload in events:
        if kind == "assistant" and not review.next_assistant and payload.strip():
            review.next_assistant = payload[:TEXT_LIMIT]
        elif kind == "edit":
            tools += 1
            if payload not in review.edits_after:
                review.edits_after.append(payload)
            if tools >= FOLLOW_TOOL_CALLS:
                break
        elif kind == "tool":
            tools += 1
            for f in _PATCH_FILE.findall(payload):
                f = f.strip().rstrip("\\")
                if f not in review.edits_after:
                    review.edits_after.append(f)
            if re.search(r"\b(pytest|cargo test|npm test|uv run pytest)\b", payload):
                review.tests_after += 1
            if tools >= FOLLOW_TOOL_CALLS:
                break


# ---------------------------------------------------------------------------- Claude
def reviews_from_claude(path: Path) -> list[Review]:
    rows = list(_rows(path))
    cwd = next((d.get("cwd") for _, d in rows if d.get("cwd")), None)
    repo = _repo(cwd)
    pending: dict[str, Review] = {}  # tool_use_id -> review
    by_agent: dict[str, Review] = {}
    done: list[tuple[int, Review]] = []  # (row index where report arrived, review)
    for idx, (n, d) in enumerate(rows):
        t = d.get("type")
        msg = d.get("message") or {}
        content = msg.get("content")
        if t == "assistant" and isinstance(content, list):
            for it in content:
                if it.get("type") == "tool_use" and it.get("name") in ("Agent", "Task"):
                    inp = it.get("input") or {}
                    desc = f"{inp.get('description', '')} {inp.get('subagent_type', '')}"
                    if REVIEW_WORDS.search(desc):
                        pending[it["id"]] = Review(
                            source="claude",
                            session_id=path.stem,
                            session_path=str(path),
                            repo=repo,
                            ref=f"L{n}",
                            ts=d.get("timestamp"),
                            kind="claude-agent",
                            request=(inp.get("description", "") + "\n" + inp.get("prompt", ""))[
                                :TEXT_LIMIT
                            ],
                        )
        elif t == "user" and isinstance(content, list):
            for it in content:
                if it.get("type") != "tool_result" or it.get("tool_use_id") not in pending:
                    continue
                rev = pending.pop(it["tool_use_id"])
                text = _text_of(it.get("content"))
                if (m := _AGENT_ID.search(text)) and "launched" in text.lower():
                    by_agent[m.group(1)] = rev  # background agent: report arrives later
                    continue
                if m := _DELIVERED_AS_MESSAGE.search(text):
                    by_agent[m.group(1)] = rev  # report is in a hand-back message
                    continue
                rev.finish(text)
                done.append((idx, rev))
        elif t == "queue-operation" and d.get("operation") == "enqueue":
            m = _HANDBACK.match(str(d.get("content") or ""))
            if m and m.group(1) in by_agent:
                rev = by_agent.pop(m.group(1))
                rev.finish(m.group(2))
                done.append((idx, rev))

    out = []
    for idx, rev in done:
        events = []
        for _, d in rows[idx + 1 :]:
            if d.get("type") != "assistant":
                continue
            for it in (d.get("message") or {}).get("content") or []:
                if it.get("type") == "text":
                    events.append(("assistant", it.get("text", "")))
                elif it.get("type") == "tool_use":
                    inp = it.get("input") or {}
                    if it.get("name") in _EDIT_TOOL_NAMES and inp.get("file_path"):
                        events.append(("edit", str(inp["file_path"])))
                    else:
                        events.append(("tool", json.dumps(inp)))
            if len(events) > FOLLOW_TOOL_CALLS + 5:
                break
        _track_after(rev, events)
        out.append(rev)
    return out


# ---------------------------------------------------------------------------- Codex
def _codex_output_text(payload: dict) -> str:
    out = payload.get("output")
    if isinstance(out, str):
        try:
            parsed = json.loads(out)
            if isinstance(parsed, dict) and "result" in parsed:
                return str(parsed["result"])
        except json.JSONDecodeError:
            pass
        return out
    return _text_of(out)


def _review_chunk(text: str) -> str:
    """From a multiplexed code-mode output, keep the part that looks like a review."""
    m = re.search(r'"result"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        try:
            return json.loads(f'"{m.group(1)}"')
        except json.JSONDecodeError:
            return m.group(1)
    i = text.find("## ")
    return text[i:] if i >= 0 else text


def reviews_from_codex(path: Path) -> list[Review]:
    rows = list(_rows(path))
    meta = next((d.get("payload") or {} for _, d in rows if d.get("type") == "session_meta"), {})
    if meta.get("thread_source") == "subagent":
        return []
    repo = _repo(meta.get("cwd"))
    calls: dict[str, Review] = {}
    cells: dict[str, Review] = {}  # code-mode cell still running -> review
    done: list[tuple[int, Review]] = []
    for idx, (n, d) in enumerate(rows):
        if d.get("type") != "response_item":
            continue
        p = d.get("payload") or {}
        ptype = p.get("type")
        if ptype in ("function_call", "custom_tool_call"):
            args = str(p.get("arguments") or p.get("input") or "")
            direct = "review_with_context" in (p.get("name") or "")
            if p.get("name") == "wait" and cells:
                m = re.search(r'"cell_id"\s*:\s*"?(\d+)', args)
                if m and m.group(1) in cells:
                    calls[p.get("call_id")] = cells.pop(m.group(1))
                continue
            if direct or "review_with_context(" in args:
                calls[p.get("call_id")] = Review(
                    source="codex",
                    session_id=meta.get("id", path.stem),
                    session_path=str(path),
                    repo=repo,
                    ref=f"L{n}",
                    ts=d.get("timestamp"),
                    kind="review-mcp",
                    request=args[:TEXT_LIMIT],
                )
        elif ptype in ("function_call_output", "custom_tool_call_output"):
            rev = calls.pop(p.get("call_id"), None)
            if rev is None:
                continue
            text = _codex_output_text(p)
            running = _CELL_RUNNING.search(text)
            if running and '"result"' not in text and "## " not in text:
                cells[running.group(1)] = rev  # result arrives through a later `wait`
                continue
            rev.finish(text if rev.request.startswith("{") else _review_chunk(text))
            done.append((idx, rev))
    out = []
    for idx, rev in done:
        events = []
        for _, d in rows[idx + 1 :]:
            p = d.get("payload") or {}
            if d.get("type") != "response_item":
                continue
            if p.get("type") == "message" and p.get("role") == "assistant":
                events.append(("assistant", _text_of(p.get("content"))))
            elif p.get("type") in ("function_call", "custom_tool_call"):
                events.append(("tool", str(p.get("arguments") or p.get("input") or "")))
            if len(events) > FOLLOW_TOOL_CALLS + 5:
                break
        _track_after(rev, events)
        out.append(rev)
    return out


def iter_reviews(
    codex_dir: Path = Path("~/.codex/sessions"), claude_dir: Path = Path("~/.claude/projects")
) -> Iterator[Review]:
    for f in sorted(codex_dir.expanduser().rglob("*.jsonl")):
        yield from reviews_from_codex(f)
    for f in sorted(claude_dir.expanduser().glob("*/*.jsonl")):
        yield from reviews_from_claude(f)


def write_reviews(out_path: Path, repos: list[str] | None = None) -> dict:
    """Extract reviews (failed ones excluded) to JSONL with secrets redacted."""
    from collections import Counter

    from fitting_room.miner.output import redact

    revs = [r for r in iter_reviews() if not repos or r.repo in repos]
    usable = [r for r in revs if not r.failed]
    body = "".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n" for r in usable)
    red = redact(body)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(red.text)
    return {
        "reviews": len(revs),
        "failed_excluded": len(revs) - len(usable),
        "written": len(usable),
        "with_edits_after": sum(1 for r in usable if r.edits_after),
        "by_kind_repo": dict(Counter(f"{r.kind}:{r.repo}" for r in usable)),
        "redacted": red.count,
    }
