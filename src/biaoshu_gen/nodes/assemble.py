"""节点 10：拼装标书草稿 docx（纯代码，无 LLM）。"""
from pathlib import Path

from docx import Document

from ..docx_io import append_docx, copy_docx, markdown_to_docx
from ..state import BidState, run_dir


def assemble_node(state: BidState) -> dict:
    out_dir = run_dir(state) / "07_draft"
    out_dir.mkdir(parents=True, exist_ok=True)
    version = state.draft_version + 1
    dest = out_dir / f"标书草稿_v{version}.docx"

    if state.template_docx_path and Path(state.template_docx_path).exists():
        doc = copy_docx(Path(state.template_docx_path), dest)     # 模板为底稿
    else:
        doc = Document()
        if state.metadata and state.metadata.project_name:
            doc.add_heading(f"{state.metadata.project_name} 投标文件", level=0)

    body_md = Path(state.body_md_path).read_text(encoding="utf-8")
    doc.add_page_break()
    markdown_to_docx(doc, "# 技术方案\n\n" + body_md)
    for p in (state.forms_docx_path, state.deviation_docx_path, state.commercial_docx_path):
        if p and Path(p).exists():
            doc.add_page_break()
            append_docx(doc, Path(p))
    doc.save(str(dest))

    (out_dir / "latest.txt").write_text(str(version), encoding="utf-8")
    md_path = out_dir / f"标书草稿_v{version}.md"
    md_path.write_text(body_md + "\n\n（已并入填充产物：forms / deviation / commercial docx）\n",
                       encoding="utf-8")
    return {"draft_docx_path": str(dest), "draft_md_path": str(md_path), "draft_version": version}
