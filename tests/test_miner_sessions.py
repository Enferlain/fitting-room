import json
import sqlite3
from pathlib import Path

from fitting_room.miner.sessions import (
    HUMAN,
    TOOL,
    iter_sessions,
    read_claude,
    read_codex,
    read_hermes,
    read_omp,
)


def jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def codex_rows(subagent=False):
    meta = {
        "id": "c1",
        "cwd": "/home/u/Projects/hcom",
        "timestamp": "2026-10-01T10:00:00Z",
        "git": {"commit_hash": "abc123", "branch": "main"},
        "thread_source": "subagent" if subagent else "user",
    }
    msg = lambda role, text: {  # noqa: E731
        "type": "response_item",
        "timestamp": "2026-10-01T10:00:01Z",
        "payload": {"type": "message", "role": role, "content": [{"text": text}]},
    }
    return [
        {"type": "session_meta", "payload": meta},
        msg("user", "# AGENTS.md instructions for /home/u/Projects/hcom\n..."),
        msg("user", "<environment_context>\n<cwd>x</cwd>"),
        msg("user", "Fix the flaky retry test in the relay"),
        {
            "type": "response_item",
            "timestamp": "2026-10-01T10:00:02Z",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": "cargo test relay"}),
            },
        },
        msg("assistant", "Done."),
    ]


def test_codex_reader_filters_injected_context_and_reads_meta(tmp_path):
    s = read_codex(jsonl(tmp_path / "r.jsonl", codex_rows()))
    assert (s.cwd, s.commit, s.branch, s.is_subagent) == (
        "/home/u/Projects/hcom",
        "abc123",
        "main",
        False,
    )
    assert [m.text for m in s.human_messages] == ["Fix the flaky retry test in the relay"]
    tool = next(m for m in s.messages if m.role == TOOL)
    assert tool.tool_name == "exec_command" and tool.tool_args == "cargo test relay"
    assert s.human_messages[0].ref == "L4"


def test_codex_subagent_flagged(tmp_path):
    assert read_codex(jsonl(tmp_path / "r.jsonl", codex_rows(subagent=True))).is_subagent


def test_claude_reader(tmp_path):
    base = {"cwd": "/home/u/Projects/sd-scripts", "gitBranch": "dev", "isSidechain": False}
    rows = [
        {**base, "type": "user", "timestamp": "t1", "message": {"content": "Add LoRA dropout"}},
        {**base, "type": "user", "timestamp": "t1", "message": {"content": "<command-name>/x"}},
        {
            **base,
            "type": "assistant",
            "timestamp": "t2",
            "message": {
                "model": "claude-x",
                "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py"}}],
            },
        },
        {
            **base,
            "type": "user",
            "timestamp": "t3",
            "message": {"content": [{"type": "tool_result", "content": "ok"}]},
        },
        {
            **base,
            "type": "user",
            "timestamp": "t4",
            "message": {"content": "no, use the config flag"},
        },
    ]
    s = read_claude(jsonl(tmp_path / "p" / "s1.jsonl", rows))
    assert (s.cwd, s.branch, s.commit, s.model) == (
        "/home/u/Projects/sd-scripts",
        "dev",
        None,
        "claude-x",
    )
    assert [m.text for m in s.human_messages] == ["Add LoRA dropout", "no, use the config flag"]
    assert [m.tool_args for m in s.messages if m.role == TOOL] == ["a.py"]


def test_omp_reader(tmp_path):
    rows = [
        {
            "type": "session",
            "id": "o1",
            "cwd": "/home/u/Projects/data-processing",
            "timestamp": "t0",
        },
        {"type": "model_change", "model": "zai/glm-5.3"},
        {
            "type": "message",
            "timestamp": "t1",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Plan the search policy"}],
            },
        },  # noqa: E501
        {
            "type": "message",
            "timestamp": "t2",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "toolCall", "name": "bash", "arguments": {"command": "bd ready"}}
                ],
            },
        },  # noqa: E501
    ]
    s = read_omp(jsonl(tmp_path / "x" / "o.jsonl", rows))
    assert (s.cwd, s.model) == ("/home/u/Projects/data-processing", "zai/glm-5.3")
    assert s.human_messages[0].text == "Plan the search policy"
    assert [(m.tool_name, m.tool_args) for m in s.messages if m.role == TOOL] == [
        ("bash", "bd ready")
    ]


def make_hermes_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE sessions (id TEXT, cwd TEXT, git_branch TEXT, git_repo_root TEXT,
            parent_session_id TEXT, started_at REAL, model TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,
            content TEXT, tool_calls TEXT, timestamp REAL);
        INSERT INTO sessions VALUES ('h1', '/home/u/Projects/hcom', 'main', NULL, NULL, 1790000000, 'm');
        INSERT INTO sessions VALUES ('h2', NULL, NULL, NULL, 'h1', 1790000100, 'm');
        INSERT INTO messages VALUES (1, 'h1', 'user', 'Wire the mail listener', NULL, 1790000001);
        INSERT INTO messages VALUES (2, 'h1', 'assistant', '',
            '[{"function": {"name": "terminal", "arguments": "{\\"command\\": \\"pytest -q\\"}"}}]',
            1790000002);
        """
    )
    con.commit()
    con.close()
    return path


def test_hermes_reader_read_only(tmp_path):
    db = make_hermes_db(tmp_path / "state.sqlite")
    before = db.stat().st_mtime_ns
    sessions = list(read_hermes(db))
    assert db.stat().st_mtime_ns == before
    h1, h2 = sessions
    assert h1.cwd == "/home/u/Projects/hcom" and not h1.is_subagent
    assert h1.started.startswith("2026-")
    assert [m.text for m in h1.human_messages] == ["Wire the mail listener"]
    assert [m.tool_args for m in h1.messages if m.role == TOOL] == ["pytest -q"]
    assert h2.is_subagent


def test_iter_sessions_all_sources(tmp_path):
    jsonl(tmp_path / "codex" / "2026" / "r.jsonl", codex_rows())
    jsonl(
        tmp_path / "claude" / "p" / "s.jsonl",
        [{"type": "user", "timestamp": "t", "cwd": "/x", "message": {"content": "hi"}}],
    )  # noqa: E501
    jsonl(
        tmp_path / "claude" / "p" / "s" / "subagents" / "a.jsonl",
        [{"type": "user", "timestamp": "t", "message": {"content": "sub"}}],
    )  # noqa: E501
    jsonl(tmp_path / "omp" / "d" / "o.jsonl", [{"type": "session", "id": "o", "cwd": "/y"}])
    db = make_hermes_db(tmp_path / "state.sqlite")
    sources = {
        "codex": tmp_path / "codex",
        "claude": tmp_path / "claude",
        "omp": tmp_path / "omp",
        "hermes": db,
    }  # noqa: E501
    found = list(iter_sessions(sources))
    assert sorted({s.source for s in found}) == ["claude", "codex", "hermes", "omp"]
    assert sum(s.source == "claude" for s in found) == 1  # subagents/ dir not read
    assert all(m.role != HUMAN or m.text for s in found for m in s.messages)
