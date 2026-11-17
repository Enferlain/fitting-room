import json
from pathlib import Path

from fitting_room.miner.reviews import reviews_from_claude, reviews_from_codex


def jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


REVIEW = "## Code Review\n\n### Findings\n1. **High:** off-by-one in the window loop." + " x" * 200


def test_codex_direct_review_and_followup(tmp_path):
    rows = [
        {"type": "session_meta", "payload": {"id": "c1", "cwd": str(tmp_path)}},
        {
            "type": "response_item",
            "timestamp": "t1",
            "payload": {
                "type": "function_call",
                "name": "review_with_context",
                "call_id": "a",
                "arguments": '{"diff_target":"staged"}',
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "a",
                "output": json.dumps({"result": REVIEW}),
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"text": "Valid finding, fixing the loop."}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "input": "*** Begin Patch\n*** Update File: src/window.py\n@@",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "review_with_context",
                "call_id": "b",
                "arguments": "{}",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "b",
                "output": json.dumps({"result": "Error: review timed out after 240s"}),
            },
        },
    ]
    good, failed = reviews_from_codex(jsonl(tmp_path / "r.jsonl", rows))
    assert good.report.startswith("## Code Review") and not good.failed
    assert good.next_assistant == "Valid finding, fixing the loop."
    assert good.edits_after == ["src/window.py"]
    assert failed.failed


def test_claude_background_agent_handback(tmp_path):
    base = {"cwd": str(tmp_path), "isSidechain": False}
    rows = [
        {
            **base,
            "type": "assistant",
            "timestamp": "t1",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "Agent",
                        "input": {"description": "Review the kernel diff", "prompt": "review it"},
                    }
                ]
            },
        },
        {
            **base,
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu1",
                        "content": "Async agent launched successfully.\nagentId: abcdef0123 (internal)",
                    }
                ]
            },
        },
        {
            "type": "queue-operation",
            "operation": "enqueue",
            "content": '<agent-message from="abcdef0123"> [Subagent hand-back] The text below is the final report.\n\n'
            + REVIEW,
        },
        {
            **base,
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Agree with finding 1."},
                    {
                        "type": "tool_use",
                        "id": "tu2",
                        "name": "Edit",
                        "input": {"file_path": "/x/kernel.py"},
                    },
                ]
            },
        },
    ]
    (rev,) = reviews_from_claude(jsonl(tmp_path / "p" / "s.jsonl", rows))
    assert rev.report.startswith("## Code Review")
    assert rev.next_assistant == "Agree with finding 1."
    assert rev.edits_after == ["/x/kernel.py"]
    assert rev.kind == "claude-agent"


def test_codex_code_mode_review_resolved_through_wait(tmp_path):
    rows = [
        {"type": "session_meta", "payload": {"id": "c2", "cwd": str(tmp_path)}},
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "x",
                "input": "await tools.mcp__review_mcp__review_with_context({})",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "x",
                "output": [
                    {
                        "type": "input_text",
                        "text": "Script running with cell ID 62\nWall time 10.0 seconds\nOutput:\n",
                    }
                ],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "wait",
                "call_id": "w1",
                "input": '{"cell_id":"62","yield_time_ms":1000}',
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "w1",
                "output": [{"type": "input_text", "text": json.dumps({"result": REVIEW})}],
            },
        },
    ]
    (rev,) = reviews_from_codex(jsonl(tmp_path / "r.jsonl", rows))
    assert rev.report.startswith("## Code Review")
