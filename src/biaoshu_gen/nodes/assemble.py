"""节点 10：拼装标书草稿 docx（纯代码，无 LLM）。

底稿 = 响应模板（标书模板.docx，含完整"投标文件的格式"章节）；
forms/commercial/deviation 是同一模板副本在各自小节填充后的结果，直接全量追加会重复拼接
同一壳结构——故按块去重合并：追加 src 中与底稿文本不同的段落/表格块。
"""
from pathlib import Path

from docx import Document

from ..docx_io import copy_docx, markdown_to_docx
from ..state import BidState, run_dir


def _block_key(block) -> str:
    """段落取全文，表格取全部单元格文本，用于去重比较。"""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    if isinstance(block, Paragraph):
        return f"p:{block.text.strip()}"
    if isinstance(block, Table):
        cells = []
        for row in block.rows:
            for c in row.cells:
                cells.append(c.text.strip())
        return "t:" + "|".join(cells)
    return ""


def append_docx_dedup(dest: Document, src_path: Path, existing: set) -> None:
    """把 src 中与底稿（existing 键集）不同的块追加到 dest，避免模板壳重复拼接。"""
    import copy as _copy

    src = Document(str(src_path))
    sect_pr = dest.element.body.sectPr
    for child in src.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag not in ("p", "tbl"):
            continue
        from docx.oxml.ns import qn
        block = None
        if tag == "p":
            from docx.text.paragraph import Paragraph
            block = Paragraph(child, src)
        else:
            from docx.table import Table
            block = Table(child, src)
        key = _block_key(block)
        if not key or key in existing:
            continue
        existing.add(key)
        el = _copy.deepcopy(child)
        if sect_pr is not None:
            sect_pr.addprevious(el)
        else:
            dest.element.body.append(el)


def assemble_node(state: BidState) -> dict:
    out_dir = run_dir(state) / "07_draft"
    out_dir.mkdir(parents=True, exist_ok=True)
    version = state.draft_version + 1
    dest = out_dir / f"标书草稿_v{version}.docx"

    # 底稿优先用填好的 forms.docx（模板壳 + 投标函/报价/资格已填），避免空模板壳重复；
    # 无 forms 时退回 标书模板.docx / 新建。
    base_src = None
    if state.forms_docx_path and Path(state.forms_docx_path).exists():
        base_src = Path(state.forms_docx_path)
    elif state.template_docx_path and Path(state.template_docx_path).exists():
        base_src = Path(state.template_docx_path)
    if base_src is not None:
        doc = copy_docx(base_src, dest)
    else:
        doc = Document()
        if state.metadata and state.metadata.project_name:
            doc.add_heading(f"{state.metadata.project_name} 投标文件", level=0)

    # 记录底稿已有块，供去重
    existing: set = set()
    for block in doc.element.body.iterchildren():
        tag = block.tag.split("}")[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph
            key = _block_key(Paragraph(block, doc))
        elif tag == "tbl":
            from docx.table import Table
            key = _block_key(Table(block, doc))
        else:
            continue
        if key:
            existing.add(key)

    body_md = Path(state.body_md_path).read_text(encoding="utf-8")
    doc.add_page_break()
    markdown_to_docx(doc, "# 技术方案\n\n" + body_md)
    for block in doc.element.body.iterchildren():
        tag = block.tag.split("}")[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph
            key = _block_key(Paragraph(block, doc))
            if key:
                existing.add(key)

    # 去重追加：commercial（商务部分内容）与 deviation（偏离表）
    for p in (state.commercial_docx_path, state.deviation_docx_path):
        if p and Path(p).exists():
            doc.add_page_break()
            append_docx_dedup(doc, Path(p), existing)
    doc.save(str(dest))

    (out_dir / "latest.txt").write_text(str(version), encoding="utf-8")
    md_path = out_dir / f"标书草稿_v{version}.md"
    md_path.write_text(body_md + "\n\n（已并入填充产物：forms / deviation / commercial docx）\n",
                       encoding="utf-8")
    return {"draft_docx_path": str(dest), "draft_md_path": str(md_path), "draft_version": version}
