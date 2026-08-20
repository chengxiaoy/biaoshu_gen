from pathlib import Path

from biaoshu_gen.nodes import extract_template as et
from biaoshu_gen.state import BidState, run_dir


def _prepare(tmp_path: Path, with_sidecar: bool):
    monkeypatch_dir = tmp_path
    tender = tmp_path / "t.docx"
    tender.write_bytes(b"fake-tender-docx")
    state = BidState(run_id="run-1", tender_path=str(tender))
    d = run_dir(state) / "01_parse"
    d.mkdir(parents=True)
    (d / "tender.md").write_text("# 招标公告", encoding="utf-8")
    if with_sidecar:
        sidecar = tmp_path / "投标模板.docx"
        sidecar.write_bytes(b"fake-sidecar")
        state = state.model_copy(update={"template_docx_path": str(sidecar)})
    return state


def _run(state, captured):
    def fake_run(task):
        captured["prompt"] = task.prompt
        captured["cwd"] = task.cwd
        for p in task.expected_outputs:
            p.write_bytes(b"fake") if p.suffix == ".docx" else p.write_text("内容", encoding="utf-8")
        return task.expected_outputs
    return fake_run


def test_extract_template_produces_docx_from_tender(tmp_path: Path, monkeypatch):
    """无随附模板：招标 docx 入工作区，产出可填写 标书模板.docx 并写入 state。"""
    monkeypatch.chdir(tmp_path)
    state = _prepare(tmp_path, with_sidecar=False)
    captured = {}
    monkeypatch.setattr(et, "run_harness_task", _run(state, captured))

    updates = et.extract_template_node(state)
    ws = run_dir(state) / "02_template"
    assert (ws / "tender.md").read_text(encoding="utf-8") == "# 招标公告"
    assert (ws / "招标文件.docx").exists()                       # 招标原件入工作区
    assert (ws / "标书模板.docx").exists()                       # 提取出的模板
    assert updates["template_docx_path"] == str(ws / "标书模板.docx")
    assert "投标文件的格式" in captured["prompt"]


def test_extract_template_with_sidecar_reference(tmp_path: Path, monkeypatch):
    """随附模板作为参考入工作区（投标模板参考.docx），产出仍为提取的 标书模板.docx。"""
    monkeypatch.chdir(tmp_path)
    state = _prepare(tmp_path, with_sidecar=True)
    captured = {}
    monkeypatch.setattr(et, "run_harness_task", _run(state, captured))

    updates = et.extract_template_node(state)
    ws = run_dir(state) / "02_template"
    assert (ws / "投标模板参考.docx").exists()
    assert "投标模板参考.docx" in captured["prompt"]
    assert updates["template_docx_path"] == str(ws / "标书模板.docx")
