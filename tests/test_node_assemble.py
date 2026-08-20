from pathlib import Path

from docx import Document

from biaoshu_gen.nodes import assemble as asm
from biaoshu_gen.schemas import TenderMetadata
from biaoshu_gen.state import BidState, run_dir


def _make_docx(path: Path, text: str, with_table: bool = False) -> None:
    d = Document()
    d.add_heading(text, level=1)
    if with_table:
        t = d.add_table(rows=1, cols=2)
        t.cell(0, 0).text = "名称"
        t.cell(0, 1).text = "数量"
    d.save(path)


def _state(tmp_path: Path, monkeypatch, version: int = 0) -> BidState:
    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    body = d / "05_body"
    body.mkdir(parents=True, exist_ok=True)
    (body / "body.md").write_text("# 总体方案\n\n本章内容。", encoding="utf-8")
    for name in ("forms", "deviation", "commercial"):
        p = d / "06_fill" / name / f"{name}.docx"
        p.parent.mkdir(parents=True, exist_ok=True)
        _make_docx(p, name, with_table=(name == "forms"))
    return BidState(
        run_id="run-1",
        metadata=TenderMetadata(project_name="演示项目"),
        body_md_path=str(body / "body.md"),
        forms_docx_path=str(d / "06_fill/forms/forms.docx"),
        deviation_docx_path=str(d / "06_fill/deviation/deviation.docx"),
        commercial_docx_path=str(d / "06_fill/commercial/commercial.docx"),
        draft_version=version,
    )


def test_assemble_uses_filled_forms_as_base_and_dedups(tmp_path: Path, monkeypatch):
    """底稿 = forms.docx（模板壳已填），commercial/deviation 去重追加不重复壳。"""
    state = _state(tmp_path, monkeypatch)
    updates = asm.assemble_node(state)
    dest = Path(updates["draft_docx_path"])
    assert dest.name == "标书草稿_v1.docx" and dest.exists()
    assert (run_dir(state) / "07_draft" / "latest.txt").read_text(encoding="utf-8") == "1"
    doc = Document(str(dest))
    texts = "\n".join(p.text for p in doc.paragraphs)
    assert "forms" in texts and "总体方案" in texts
    assert "commercial" in texts and "deviation" in texts   # 去重后仍含填充内容
    assert texts.count("forms") == 1 and texts.count("commercial") == 1   # 壳不重复
    assert len(doc.tables) == 1                             # forms 表格仅一份
    assert updates["draft_version"] == 1


def test_assemble_version_increments(tmp_path: Path, monkeypatch):
    state = _state(tmp_path, monkeypatch, version=1)
    updates = asm.assemble_node(state)
    assert Path(updates["draft_docx_path"]).name == "标书草稿_v2.docx"
    assert (run_dir(state) / "07_draft" / "latest.txt").read_text(encoding="utf-8") == "2"


def test_assemble_falls_back_to_template_when_no_forms(tmp_path: Path, monkeypatch):
    tpl = tmp_path / "标书模板.docx"
    _make_docx(tpl, "模板标题页")
    state = _state(tmp_path, monkeypatch)
    state = state.model_copy(update={
        "template_docx_path": str(tpl),
        "forms_docx_path": "",                              # forms 缺失 -> 用模板底稿
    })
    updates = asm.assemble_node(state)
    doc = Document(updates["draft_docx_path"])
    texts = "\n".join(p.text for p in doc.paragraphs)
    assert "模板标题页" in texts and "总体方案" in texts
    assert "commercial" in texts
