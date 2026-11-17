"""Split sessions into candidate task episodes (spec: session-mining; design D7).

An *episode* is one substantive human request plus the work until the next one.
Short or continuation messages ("continue please", "and the tests?") attach to the
current episode as follow-ups; follow-ups that push back are flagged as corrections,
which later become checklist items and failure modes for task authoring.

The heuristics here only *suggest*: which candidates become tasks is decided by the
human at checkpoint 1.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path

from fitting_room.miner.sessions import ASSISTANT, HUMAN, TOOL, Message, Session

SUBSTANTIVE_MIN_CHARS = 60

_CONTINUATION = re.compile(
    r"^\s*(continue|go on|go ahead|keep going|proceed|carry on|ok(ay)?|yes|yep|sure|"
    r"thanks?|thank you|good( job)?|nice|great|done\??|lgtm|do it|go)\b"
    r"[\s.!,]*(please|pls)?[\s.!]*$",
    re.I,
)
_CORRECTION = re.compile(
    r"^\s*(no\b|nope|wrong|stop\b|wait\b|actually\b|undo|revert|instead\b)"
    r"|\b(why did you|why are you|why would you|you didn'?t|you did not|that'?s (not|wrong)|"
    r"isn'?t (right|what)|i (said|asked|told you|meant)|are you serious|don'?t\b|"
    r"should(n'?t)? have)",
    re.I,
)
_TEST_CMD = re.compile(
    r"\b(pytest|cargo (test|nextest)|npm (run )?test|pnpm test|go test|uv run pytest|"
    r"python -m pytest|unittest|ctest|bun test)\b"
)
_GIT_COMMIT = re.compile(r"\bgit\b[^|;&]*\bcommit\b")
_EDIT_TOOLS = {"edit", "write", "multiedit", "apply_patch", "str_replace", "notebookedit", "patch"}
# Patch headers, either on real lines or inside a code string with escaped newlines
# (Codex code mode: tools.apply_patch("*** Begin Patch\\n*** Update File: x\\n...")).
_PATCH_FILE = re.compile(r"\*\*\* (?:Update|Add|Delete) File: ((?:(?!\\n)[^\n\"'`])+)")


def is_substantive(text: str) -> bool:
    t = text.strip()
    if _CONTINUATION.match(t):
        return False
    return len(t) >= SUBSTANTIVE_MIN_CHARS or "\n" in t


def is_correction(text: str) -> bool:
    return bool(_CORRECTION.search(text))


@dataclass
class FollowUp:
    ref: str
    text: str
    correction: bool  # keyword heuristic; superseded by `label` once classified
    prev_assistant: str = ""  # end of the assistant message before this follow-up
    next_assistant: str = ""  # start of the assistant reply after it
    label: str | None = None  # model_error | misunderstanding | scope_change | question | ...
    label_reason: str | None = None


@dataclass
class Episode:
    source: str
    session_id: str
    session_path: str
    index: int  # episode number within the session
    repo: str | None
    repo_root: str | None
    cwd: str | None
    branch: str | None
    start: str | None
    request: str
    request_ref: str
    commit: str | None = None
    commit_inferred: bool = False
    model: str | None = None
    follow_ups: list[FollowUp] = field(default_factory=list)
    tool_calls: int = 0
    files_edited: list[str] = field(default_factory=list)
    test_runs: int = 0
    git_commits: int = 0
    suggested_track: str = "investigative"

    @property
    def corrections(self) -> list[FollowUp]:
        """Follow-ups where the model was wrong: the GLM label when one exists
        (model_error), otherwise the keyword heuristic."""
        return [
            f
            for f in self.follow_ups
            if (f.label == "model_error") or (f.label is None and f.correction)
        ]

    @property
    def episode_id(self) -> str:
        return f"{self.source}:{self.session_id}#{self.index}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["episode_id"] = self.episode_id
        d["n_corrections"] = len(self.corrections)
        return d


@cache
def repo_root_of(cwd: str | None) -> str | None:
    if not cwd or not Path(cwd).is_dir():
        return None
    out = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def infer_commit(repo_root: str | None, branch: str | None, when: str | None) -> str | None:
    """Last commit on ``branch`` (or HEAD) at or before ``when`` (ISO time)."""
    if not repo_root or not when:
        return None
    for ref in [branch, "HEAD"] if branch else ["HEAD"]:
        out = subprocess.run(
            ["git", "-C", repo_root, "rev-list", "-1", f"--before={when}", ref],
            capture_output=True,
            text=True,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return None


def _edited_files(msg: Message) -> list[str]:
    """Files a tool call edited. Patch headers count wherever they appear, because newer
    Codex runs everything (including apply_patch) inside one code-mode `exec` tool."""
    found = [f.strip().rstrip("\\") for f in _PATCH_FILE.findall(msg.tool_args)]
    if found:
        return found
    name = (msg.tool_name or "").lower()
    if name in _EDIT_TOOLS and msg.tool_args and "\n" not in msg.tool_args:
        return [msg.tool_args]
    return []


def _relative(path: str, root: str | None) -> str:
    if root and path.startswith(root.rstrip("/") + "/"):
        return path[len(root.rstrip("/")) + 1 :]
    return path


def _account_tool(ep: Episode, msg: Message) -> None:
    ep.tool_calls += 1
    for f in (_relative(p, ep.repo_root) for p in _edited_files(msg)):
        if f not in ep.files_edited:
            ep.files_edited.append(f)
    if _TEST_CMD.search(msg.tool_args):
        ep.test_runs += 1
    if _GIT_COMMIT.search(msg.tool_args):
        ep.git_commits += 1


CONTEXT_CHARS = 1200


def split_episodes(session: Session) -> list[Episode]:
    """Split one session into episodes. Messages before the first substantive request
    (e.g. a bare "continue") are attached to the first episode as follow-ups."""
    root = repo_root_of(session.cwd)
    repo = Path(root).name if root else (Path(session.cwd).name if session.cwd else None)
    episodes: list[Episode] = []
    pending: list[FollowUp] = []
    current: Episode | None = None
    last_assistant = ""
    awaiting_reply: list[FollowUp] = []
    for msg in session.messages:
        if msg.role == ASSISTANT:
            last_assistant = msg.text
            for fu in awaiting_reply:
                fu.next_assistant = msg.text[:CONTEXT_CHARS]
            awaiting_reply = []
        if msg.role == HUMAN:
            if is_substantive(msg.text) and not (current and is_correction(msg.text)):
                current = Episode(
                    source=session.source,
                    session_id=session.session_id,
                    session_path=session.path,
                    index=len(episodes),
                    repo=repo,
                    repo_root=root,
                    cwd=session.cwd,
                    branch=session.branch,
                    start=msg.ts or session.started,
                    request=msg.text.strip(),
                    request_ref=msg.ref,
                    model=session.model,
                    follow_ups=pending,
                )
                pending = []
                episodes.append(current)
            else:
                fu = FollowUp(
                    msg.ref,
                    msg.text.strip(),
                    is_correction(msg.text),
                    prev_assistant=last_assistant[-CONTEXT_CHARS:],
                )
                awaiting_reply.append(fu)
                (current.follow_ups if current else pending).append(fu)
        elif msg.role == TOOL and current:
            _account_tool(current, msg)

    for ep in episodes:
        if ep.index == 0 and session.commit:
            ep.commit = session.commit
        else:
            ep.commit = infer_commit(root, session.branch, ep.start)
            ep.commit_inferred = ep.commit is not None
        ep.suggested_track = "coding" if ep.files_edited else "investigative"
    return episodes
