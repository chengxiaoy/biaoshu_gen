"""docx 与 Markdown 的双向转换、模板复制、文档合并。"""
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.table import Table
from docx.text.paragraph import Paragraph


def _iter_block_items(doc: DocumentType):
    """按文档真实顺序产出段落与表格。"""
    from docx.oxml.ns import qn
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _table_md(table: Table) -> str:
    lines = []
    for row in table.rows:
        cells = [c.text.replace("\n", " ").replace("|", "/").strip() for c in row.cells]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


@dataclass
class DocxSection:
    """docx 按标题切出的章节。level=0 表示首个标题前的前言。"""
    level: int          # 0=前言, 1~4=Heading N
    title: str
    content: str        # 本节正文 Markdown（含表格）


_HEADING_RE = re.compile(r"(?:heading|标题)\s*(\d)", re.IGNORECASE)


def docx_to_sections(path: Path) -> list[DocxSection]:
    doc = Document(str(path))
    sections: list[DocxSection] = []
    cur: DocxSection | None = None

    def flush(text: str) -> None:
        nonlocal cur
        if cur is None:
            cur = DocxSection(0, "(前言)", "")
        if text:
            cur.content = (cur.content + "\n\n" + text).strip()

    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            m = _HEADING_RE.match((block.style.name or "").strip())
            if m and text:
                if cur is not None:
                    sections.append(cur)
                cur = DocxSection(int(m.group(1)), text, "")
            else:
                flush(text)
        else:
            flush(_table_md(block))
    if cur is not None:
        sections.append(cur)
    return sections


def docx_to_markdown(path: Path) -> str:
    parts: list[str] = []
    for s in docx_to_sections(path):
        if s.level:
            parts.append("#" * s.level + " " + s.title)
        if s.content:
            parts.append(s.content)
    return "\n\n".join(parts) + "\n"


def markdown_to_docx(doc: DocumentType, md: str) -> None:
    """极量版 Markdown → docx：标题/列表/段落（POC 够用）。"""
    for line in md.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            doc.add_heading(m.group(2), level=len(m.group(1)))
        elif s.startswith(("- ", "* ")):
            doc.add_paragraph(s[2:], style="List Bullet")
        elif re.match(r"^\d+\.\s+", s):
            doc.add_paragraph(re.sub(r"^\d+\.\s+", "", s), style="List Number")
        else:
            doc.add_paragraph(re.sub(r"\*\*(.+?)\*\*", r"\1", s))


def append_docx(dest: DocumentType, src_path: Path) -> None:
    """把 src 文档 body 的段落/表格深拷贝追加到 dest（跨文档移动需要 deepcopy）。"""
    import copy as _copy

    src = Document(str(src_path))
    sect_pr = dest.element.body.sectPr
    for child in src.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag in ("p", "tbl"):
            el = _copy.deepcopy(child)
            if sect_pr is not None:
                sect_pr.addprevious(el)   # sectPr 必须是 body 最后一个子元素（ECMA-376）
            else:
                dest.element.body.append(el)


def copy_docx(src: Path, dest: Path) -> DocumentType:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return Document(str(dest))
