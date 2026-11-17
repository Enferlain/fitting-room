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


def test_label_reviews_parallel_and_cached(tmp_path):
    from fitting_room.miner.review_labels import label_reviews, review_key

    recs = [
        {
            "review_id": f"codex:s@L{i}",
            "request": "r",
            "report": f"report {i}",
            "next_assistant": "ok",
            "edits_after": [],
            "tests_after": 0,
        }
        for i in range(7)
    ]
    src = tmp_path / "reviews.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in recs))

    def answer(prompt):
        ids = [ln.split("id: ")[1] for ln in prompt.splitlines() if ln.startswith("### id: ")]
        return json.dumps(
            [
                {"id": i, "label": "real_bug_fixed", "bug": "off by one", "reason": "fixed"}
                for i in ids
            ]
        )

    cache = tmp_path / "labels.jsonl"
    stats = label_reviews(src, cache, parallel=2, caller=answer, log=lambda _: None)
    assert stats["labelled"] == 7 and stats["model_calls"] == 3
    again = label_reviews(src, cache, parallel=2, caller=lambda _: 1 / 0, log=lambda _: None)
    assert again["model_calls"] == 0 and again["cached_total"] == 7
    keys = {json.loads(x)["key"] for x in cache.read_text().splitlines()}
    assert keys == {review_key(r) for r in recs}


def test_review_labeller_sends_review_prompt(monkeypatch, tmp_path):
    from fitting_room.miner import classify, review_labels

    seen = {}

    def fake_call(user, *, system=classify.SYSTEM, timeout=300):
        seen["system"] = system
        return "[]"

    monkeypatch.setattr(review_labels, "call_glm", fake_call)
    src = tmp_path / "r.jsonl"
    src.write_text(
        json.dumps(
            {
                "review_id": "x",
                "request": "",
                "report": "r",
                "next_assistant": "",
                "edits_after": [],
                "tests_after": 0,
            }
        )
        + "\n"
    )
    review_labels.label_reviews(src, tmp_path / "l.jsonl", log=lambda _: None)
    assert seen["system"] is review_labels.SYSTEM


def test_review_bugs_attach_to_episode_by_time(tmp_path):
    from fitting_room.miner.episodes import Episode
    from fitting_room.miner.output import review_score
    from fitting_room.miner.pipeline import apply_review_bugs
    from fitting_room.miner.review_labels import review_key

    def ep(i, start):
        return Episode(source="codex", session_id="s", session_path="", index=i, repo="r",
                       repo_root=None, cwd=None, branch=None, start=start, request="x",
                       request_ref="L1", commit="c")  # fmt: skip

    e0, e1 = ep(0, "2026-10-01T10:00"), ep(1, "2026-10-01T12:00")
    reviews = [
        {
            "review_id": "codex:s@L5",
            "source": "codex",
            "session_id": "s",
            "ts": "2026-10-01T11:00",
            "report": "a",
        },
        {
            "review_id": "codex:s@L9",
            "source": "codex",
            "session_id": "s",
            "ts": "2026-10-01T13:00",
            "report": "b",
        },
        {
            "review_id": "codex:s@L12",
            "source": "codex",
            "session_id": "s",
            "ts": "2026-10-01T13:30",
            "report": "c",
        },
    ]
    (tmp_path / "reviews.jsonl").write_text("".join(json.dumps(r) + "\n" for r in reviews))
    labels = ["real_bug_fixed", "real_bug_unfixed", "minor_only"]
    (tmp_path / "review-labels.jsonl").write_text("".join(
        json.dumps({"key": review_key(r), "label": lab, "bug": f"bug {i}"}) + "\n"
        for i, (r, lab) in enumerate(zip(reviews, labels, strict=True))
    ))  # fmt: skip
    before = review_score(e0)
    assert apply_review_bugs([e0, e1], tmp_path) == 2
    assert [b["label"] for b in e0.review_bugs] == ["real_bug_fixed"]
    assert [b["label"] for b in e1.review_bugs] == ["real_bug_unfixed"]
    assert review_score(e0) == before + 4.0
