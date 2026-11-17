import json
from pathlib import Path

from fitting_room.miner.calibrate import score, write_sample
from fitting_room.miner.classify import cache_key


def setup(tmp_path: Path, labels: list[str]) -> Path:
    fus = [
        {
            "ref": f"L{i}",
            "text": f"follow-up {i}",
            "prev_assistant": "before",
            "next_assistant": "after",
        }
        for i in range(len(labels))
    ]
    (tmp_path / "candidates.jsonl").write_text(
        json.dumps({"episode_id": "e", "follow_ups": fus}) + "\n"
    )
    recs = [
        {
            "key": cache_key("e", f"L{i}", f"follow-up {i}"),
            "label": lab,
            "reason": f"r{i}",
            "by": "glm",
        }
        for i, lab in enumerate(labels)
    ]
    (tmp_path / "labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    return tmp_path


def test_sample_is_blind_and_weighted(tmp_path):
    d = setup(tmp_path, ["model_error"] * 5 + ["misunderstanding"] * 5 + ["question"] * 5)
    stats = write_sample(
        d / "candidates.jsonl",
        d / "labels.jsonl",
        d / "cal",
        n_error=3,
        n_misunderstanding=2,
        n_other=1,
    )
    assert stats["items"] == 6
    check = (d / "cal/check.md").read_text()
    assert "model_error" not in check and "misunderstanding" not in check.split("## Item 1")[1]
    assert sum(ln.startswith("**Agent fell short?**") for ln in check.splitlines()) == 6
    key = [json.loads(x) for x in (d / "cal/key.jsonl").read_text().splitlines()]
    assert sorted(k["label"] for k in key).count("model_error") == 3


def test_score(tmp_path):
    d = setup(tmp_path, ["model_error"] * 4 + ["question"] * 4)
    write_sample(
        d / "candidates.jsonl",
        d / "labels.jsonl",
        d / "cal",
        n_error=4,
        n_misunderstanding=0,
        n_other=4,
    )
    key = {
        k["item"]: k["label"]
        for k in map(json.loads, (d / "cal/key.jsonl").read_text().splitlines())
    }
    text = (d / "cal/check.md").read_text()
    out, item = [], 0
    for line in text.splitlines():
        if line.startswith("## Item "):
            item = int(line.split()[-1])
        if line.startswith("**Agent fell short?**"):
            # agree everywhere except: one GLM error you call "no", one question you call "yes"
            glm_err = key[item] == "model_error"
            ans = "yes" if glm_err else "no"
            if item == min(i for i, lab in key.items() if lab == "model_error"):
                ans = "no"
            if item == min(i for i, lab in key.items() if lab == "question"):
                ans = "yes"
            line = line + ans
        out.append(line)
    (d / "cal/check.md").write_text("\n".join(out))
    s = score(d / "cal")
    assert s.answered == 8 and s.unanswered == 0
    assert s.model_error_precision == 0.75 and s.missed_errors == 1
    assert s.agreement == 0.75 and abs(s.kappa - 0.5) < 1e-9
    assert len(s.disagreements) == 2
