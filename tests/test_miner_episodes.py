import json
import subprocess
from pathlib import Path

import pytest

from fitting_room.miner import output as output_mod
from fitting_room.miner.episodes import is_correction, is_substantive, split_episodes
from fitting_room.miner.output import redact
from fitting_room.miner.pipeline import mine
from fitting_room.miner.sessions import ASSISTANT, HUMAN, TOOL, Message, Session

LONG_A = "Add a dropout option to the LoRA network module and wire it through the training config"
LONG_B = (
    "Now write an investigation of why the cache invalidation happens twice per epoch in the loader"
)


def git(repo: Path, *args: str, date: str | None = None) -> str:
    env = None
    if date:
        import os

        env = {**os.environ, "GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date}
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "sd-scripts"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.invalid")
    git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("1")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "one", date="2026-10-01T09:00:00Z")
    (r / "a.txt").write_text("2")
    git(r, "commit", "-qam", "two", date="2026-10-01T11:00:00Z")
    return r


def session(repo: Path, msgs: list[Message], commit: str | None = None) -> Session:
    return Session(
        source="codex",
        session_id="s1",
        path="/x/s1.jsonl",
        cwd=str(repo),
        branch="main",
        commit=commit,
        started="2026-10-01T10:00:00Z",
        messages=msgs,
    )


def test_substantive_and_correction_heuristics():
    assert is_substantive(LONG_A)
    assert not is_substantive("continue please")
    assert not is_substantive("ok")
    assert is_substantive("fix it\nand also the tests")
    assert is_correction("no, use the config flag")
    assert is_correction("why did you remove the fallback?")
    assert is_correction("I asked for the upstream version")
    assert not is_correction("can you also add docs for this option?")


def test_split_into_episodes_with_followups_and_signals(repo):
    msgs = [
        Message(HUMAN, LONG_A, "2026-10-01T10:00:00Z", "L5"),
        Message(
            TOOL,
            "",
            "2026-10-01T10:01:00Z",
            "L6",
            "apply_patch",
            "*** Begin Patch\n*** Update File: networks/lora.py\n@@",
        ),  # fmt: skip
        Message(TOOL, "", "2026-10-01T10:02:00Z", "L7", "exec_command", "uv run pytest -q"),
        Message(HUMAN, "no, keep the old default", "2026-10-01T10:03:00Z", "L8"),
        Message(TOOL, "", "2026-10-01T10:04:00Z", "L9", "exec_command", "git commit -am fix"),
        Message(ASSISTANT, "done", "2026-10-01T10:05:00Z", "L10"),
        Message(HUMAN, "continue please", "2026-10-01T10:06:00Z", "L11"),
        Message(HUMAN, LONG_B, "2026-10-01T12:00:00Z", "L12"),
        Message(TOOL, "", "2026-10-01T12:01:00Z", "L13", "Read", "library/cache.py"),
    ]
    first, second = split_episodes(session(repo, msgs, commit="abc123"))

    assert first.request == LONG_A and first.request_ref == "L5"
    assert [(f.text, f.correction) for f in first.follow_ups] == [
        ("no, keep the old default", True),
        ("continue please", False),
    ]
    assert first.files_edited == ["networks/lora.py"]
    assert (first.tool_calls, first.test_runs, first.git_commits) == (3, 1, 1)
    assert first.suggested_track == "coding"
    assert (first.commit, first.commit_inferred) == ("abc123", False)
    assert first.repo == "sd-scripts"

    assert second.suggested_track == "investigative"
    # Starts at 12:00, so the commit at 11:00 ("two") is inferred.
    assert second.commit == git(repo, "rev-parse", "HEAD") and second.commit_inferred


def test_commit_inferred_for_first_episode_without_session_commit(repo):
    msgs = [Message(HUMAN, LONG_A, "2026-10-01T10:00:00Z", "L1")]
    (ep,) = split_episodes(session(repo, msgs))
    assert ep.commit == git(repo, "rev-parse", "HEAD~1") and ep.commit_inferred


def test_unrecoverable_commit_is_unknown(tmp_path):
    msgs = [Message(HUMAN, LONG_A, "2026-10-01T10:00:00Z", "L1")]
    (ep,) = split_episodes(session(tmp_path / "not-a-repo", msgs))
    assert ep.commit is None and not ep.commit_inferred


FAKE_KEY = "sk-proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"


def test_redaction_with_gitleaks_or_fallback(monkeypatch):
    text = f"set OPENAI_API_KEY={FAKE_KEY} then run it"
    res = redact(text)
    assert FAKE_KEY not in res.text and res.count >= 1
    monkeypatch.setattr(output_mod.shutil, "which", lambda _: None)
    res = redact(text)
    assert FAKE_KEY not in res.text and res.scanner == "regex" and res.warning


def write_codex(path: Path, cwd: str, texts: list[str], subagent=False) -> None:
    rows = [
        {
            "type": "session_meta",
            "payload": {
                "id": path.stem,
                "cwd": cwd,
                "timestamp": "2026-10-01T10:00:00Z",
                "thread_source": "subagent" if subagent else "user",
            },
        }
    ] + [
        {
            "type": "response_item",
            "timestamp": "2026-10-01T10:00:01Z",
            "payload": {"type": "message", "role": "user", "content": [{"text": t}]},
        }
        for t in texts
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_mine_filters_repos_skips_subagents_and_redacts(tmp_path, repo):
    other = tmp_path / "other-repo"
    other.mkdir()
    base = tmp_path / "codex"
    write_codex(base / "a.jsonl", str(repo), [LONG_A + f" key {FAKE_KEY}"])
    write_codex(base / "b.jsonl", str(other), [LONG_B])
    write_codex(base / "c.jsonl", str(repo), [LONG_B], subagent=True)
    out = tmp_path / "out"
    stats = mine(["sd-scripts"], out, sources={"codex": base})

    assert stats["sessions_by_source"] == {"codex": 3}
    assert stats["skipped"] == {"subagent": 1, "other_repo": 1}
    assert stats["episodes_by_repo"] == {"sd-scripts": 1}
    assert stats["redacted"] >= 1
    jsonl = (out / "candidates.jsonl").read_text()
    md = (out / "candidates.md").read_text()
    assert FAKE_KEY not in jsonl and FAKE_KEY not in md
    assert "[REDACTED]" in jsonl
    assert "## sd-scripts (1)" in md


def test_markdown_ranks_and_limits_rows(tmp_path):
    from fitting_room.miner.episodes import Episode, FollowUp
    from fitting_room.miner.output import render_markdown

    def ep(i, corrections=0, edits=0):
        return Episode(
            source="codex", session_id=f"s{i}", session_path="", index=0, repo="r",
            repo_root=None, cwd=None, branch=None, start=f"2026-10-0{i}", commit="c",
            request=f"request {i}", request_ref="L1",
            follow_ups=[FollowUp("L2", "no", True)] * corrections,
            files_edited=["f"] * edits,
        )  # fmt: skip

    eps = [ep(1), ep(2, corrections=1), ep(3, edits=1)]
    md = render_markdown(eps, {}, top=2)
    rows = [line for line in md.splitlines() if line.startswith("| ") and "`codex:" in line]
    assert len(rows) == 2
    assert "`codex:s2#0`" in rows[0] and "`codex:s3#0`" in rows[1]
    assert "| score |" in md
    assert (
        len([ln for ln in render_markdown(eps, {}, top=None).splitlines() if "`codex:" in ln]) == 3
    )


def test_codex_exec_patch_counts_as_edit(repo):
    code = (
        "await tools.apply_patch(`*** Begin Patch\n*** Add File: docs/new.md\n+hi\n*** End Patch`)"
    )
    msgs = [
        Message(HUMAN, LONG_A, "2026-10-01T10:00:00Z", "L1"),
        Message(TOOL, "", "2026-10-01T10:01:00Z", "L2", "exec", code),
    ]
    (ep,) = split_episodes(session(repo, msgs))
    assert ep.files_edited == ["docs/new.md"] and ep.suggested_track == "coding"


def test_codex_exec_escaped_patch_and_relative_paths(repo):
    code = (
        'tools.apply_patch("*** Begin Patch\\n*** Update File: '
        + str(repo)
        + '/src/events.rs\\n@@\\n+x\\n*** End Patch")'
    )
    msgs = [
        Message(HUMAN, LONG_A, "2026-10-01T10:00:00Z", "L1"),
        Message(TOOL, "", "2026-10-01T10:01:00Z", "L2", "exec", code),
    ]
    (ep,) = split_episodes(session(repo, msgs))
    assert ep.files_edited == ["src/events.rs"]
