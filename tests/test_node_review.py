from pathlib import Path

from docx import Document

from biaoshu_gen.nodes import review as rv
from biaoshu_gen.nodes import revise as rs
from biaoshu_gen.state import BidState, run_dir


def _setup(tmp_path: Path, monkeypatch) -> BidState:
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1")
    d = run_dir(state)
    parse = d / "01_parse"
    parse.mkdir(parents=True)
    (parse / "tender.md").write_text("# 招标", encoding="utf-8")
    (parse / "invalidation.yaml").write_text("items: []\n", encoding="utf-8")
    (parse / "scoring.yaml").write_text("technical_rules: []\n", encoding="utf-8")
    (d / "03_facts.yaml").write_text("schedule: 90 天\n", encoding="utf-8")
    draft = d / "07_draft" / "标书草稿_v1.docx"
    draft.parent.mkdir(parents=True)
    Document().save(draft)
    (d / "07_draft" / "标书草稿_v1.md").write_text("# 正文", encoding="utf-8")
    return state.model_copy(update={
        "draft_docx_path": str(draft),
        "draft_md_path": str(d / "07_draft" / "标书草稿_v1.md"),
        "draft_version": 1,
    })


def _fake_harness(report_text: str, produced: Path):
    def fake(task):
        produced.parent.mkdir(parents=True, exist_ok=True)
        produced.write_text(report_text, encoding="utf-8")
        return task.expected_outputs
    return fake


def test_review_parses_verdict_pass(tmp_path: Path, monkeypatch):
    state = _setup(tmp_path, monkeypatch)
    out = run_dir(state) / "08_review" / "review_round_1.md"
    monkeypatch.setattr(rv, "run_harness_task", _fake_harness(
        "## 检查\n- 各项通过\n\nVERDICT: PASS", out))
    updates = rv.review_node(state)
    assert updates["review_passed"] is True
    assert "需人工处理" not in out.read_text(encoding="utf-8")


def test_review_fail_missing_verdict_treated_as_fail(tmp_path: Path, monkeypatch):
    state = _setup(tmp_path, monkeypatch)
    out = run_dir(state) / "08_review" / "review_round_1.md"
    monkeypatch.setattr(rv, "run_harness_task", _fake_harness("没有结论行", out))
    updates = rv.review_node(state)
    assert updates["review_passed"] is False


def test_review_fail_at_cap_appends_manual_note(tmp_path: Path, monkeypatch):
    state = _setup(tmp_path, monkeypatch).model_copy(update={"revision_round": 2})
    out = run_dir(state) / "08_review" / "review_round_3.md"
    monkeypatch.setattr(rv, "run_harness_task", _fake_harness(
        "- 问题A\n\nVERDICT: FAIL", out))
    updates = rv.review_node(state)
    assert updates["review_passed"] is False
    assert "需人工处理" in out.read_text(encoding="utf-8")


def test_review_fail_below_cap_no_manual_note(tmp_path: Path, monkeypatch):
    state = _setup(tmp_path, monkeypatch).model_copy(update={"revision_round": 0})
    out = run_dir(state) / "08_review" / "review_round_1.md"
    monkeypatch.setattr(rv, "run_harness_task", _fake_harness("VERDICT: FAIL", out))
    rv.review_node(state)
    assert "需人工处理" not in out.read_text(encoding="utf-8")


def test_revise_produces_next_version(tmp_path: Path, monkeypatch):
    state = _setup(tmp_path, monkeypatch)
    state = state.model_copy(update={
        "review_report_path": str(run_dir(state) / "08_review" / "review_round_1.md")})
    (run_dir(state) / "08_review").mkdir(parents=True, exist_ok=True)
    (run_dir(state) / "08_review" / "review_round_1.md").write_text(
        "VERDICT: FAIL\n- 补充质保承诺", encoding="utf-8")
    out = run_dir(state) / "07_draft" / "标书草稿_v2.docx"

    def fake(task):
        out.write_bytes(b"fake-docx")
        return task.expected_outputs
    monkeypatch.setattr(rs, "run_harness_task", fake)

    updates = rs.revise_node(state)
    assert updates["draft_version"] == 2 and updates["revision_round"] == 1
    assert updates["draft_docx_path"] == str(out)
    assert (run_dir(state) / "07_draft" / "latest.txt").read_text(encoding="utf-8") == "2"
