from pathlib import Path

from biaoshu_gen.nodes import extract_template as et
from biaoshu_gen.state import BidState, run_dir


def test_extract_template_node(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1", tender_path="t.docx")
    d = run_dir(state) / "01_parse"
    d.mkdir(parents=True)
    (d / "tender.md").write_text("# 招标公告", encoding="utf-8")
    tpl = tmp_path / "标书模板.docx"
    tpl.write_bytes(b"fake-docx")
    state = state.model_copy(update={"template_docx_path": str(tpl)})

    captured = {}

    def fake_run(task):
        captured["prompt"] = task.prompt
        captured["cwd"] = task.cwd
        for p in task.expected_outputs:
            p.write_text("内容", encoding="utf-8")
        return task.expected_outputs
    monkeypatch.setattr(et, "run_harness_task", fake_run)

    updates = et.extract_template_node(state)
    ws = run_dir(state) / "02_template"
    assert (ws / "tender.md").read_text(encoding="utf-8") == "# 招标公告"
    assert (ws / "标书模板.docx").exists()
    assert "template.md" in captured["prompt"]
    assert updates["template_md_path"] == str(ws / "template.md")
    assert updates["template_report_path"] == str(ws / "report.md")
