"""docx 与 Markdown 的双向转换、模板复制、文档合并。"""
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def _full_text(para) -> str:
    """段落全文含修订插入(w:ins)等嵌套 run:遍历全部 w:t 后代节点。

    python-docx 的 paragraph.text 不下钻 w:ins(带修订标记的文档会抽成空文本);
    只取 w:t 天然跳过 w:delText(删除标记),等价于"按接受全部修订"阅读。
    """
    return "".join(n.text or "" for n in para._p.iter() if n.tag == qn("w:t"))


def iter_block_items(doc: DocumentType):
    """按文档真实顺序产出段落与表格。"""
    from docx.oxml.ns import qn
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


_iter_block_items = iter_block_items   # 兼容旧名（docx_to_sections 仍引用）


def table_md(table: Table) -> str:
    lines = []
    for row in table.rows:
        cells = ["\n".join(_full_text(p) for p in c.paragraphs)
                 .replace("\n", " ").replace("|", "/").strip() for c in row.cells]
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
            text = _full_text(block).strip()
            m = _HEADING_RE.match((block.style.name or "").strip())
            if m and text:
                if cur is not None:
                    sections.append(cur)
                cur = DocxSection(int(m.group(1)), text, "")
            else:
                flush(text)
        else:
            flush(table_md(block))
    if cur is not None:
        sections.append(cur)
    return sections


def sections_to_markdown(sections: list[DocxSection]) -> str:
    parts: list[str] = []
    for s in sections:
        if s.level:
            parts.append("#" * s.level + " " + s.title)
        if s.content:
            parts.append(s.content)
    return "\n\n".join(parts) + "\n"


def docx_to_markdown(path: Path) -> str:
    return sections_to_markdown(docx_to_sections(path))


def _add_styled(doc: DocumentType, text: str, style: str):
    """按样式加段落；样式缺失（常见于中文模板底稿）时回退为普通段落。"""
    try:
        return doc.add_paragraph(text, style=style)
    except KeyError:
        return doc.add_paragraph(text)


def markdown_to_docx(doc: DocumentType, md: str) -> None:
    """极量版 Markdown → docx：标题/列表/段落（POC 够用）。"""
    for line in md.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            try:
                doc.add_heading(m.group(2), level=len(m.group(1)))
            except KeyError:                      # 模板缺 Heading N 样式时回退
                doc.add_paragraph(m.group(2))
        elif s.startswith(("- ", "* ")):
            _add_styled(doc, s[2:], "List Bullet")
        elif re.match(r"^\d+\.\s+", s):
            _add_styled(doc, re.sub(r"^\d+\.\s+", "", s), "List Number")
        else:
            doc.add_paragraph(re.sub(r"\*\*(.+?)\*\*", r"\1", s))


def copy_docx(src: Path, dest: Path) -> DocumentType:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return Document(str(dest))


@dataclass
class DocxBlockRange:
    """标题区间：锚标题 + 其管辖的 body 子元素（到下一同级/更高级标题前，不含 sectPr）。"""
    title: str
    level: int
    elements: list


def docx_block_ranges(doc: DocumentType) -> list[DocxBlockRange]:
    """按标题把文档切成区间（assemble 分段定位/替换的基础）。"""
    ranges: list[DocxBlockRange] = []
    cur: DocxBlockRange | None = None
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "sectPr":
            continue                        # 分节属性固定在 body 尾部，不参与区间
        level = 0
        if tag == "p":
            para = Paragraph(child, doc)
            m = _HEADING_RE.match((para.style.name or "").strip())
            if m and para.text.strip():
                if cur is not None:
                    ranges.append(cur)
                cur = DocxBlockRange(para.text.strip(), int(m.group(1)), [child])
                continue
        if cur is None:
            cur = DocxBlockRange("(前言)", 0, [])
        cur.elements.append(child)
    if cur is not None:
        ranges.append(cur)
    return ranges


def replace_elements(old_elements: list, new_elements: list) -> None:
    """就地替换：new_elements（来自其他文档，自动深拷贝）替换 old_elements，保持原位置。"""
    import copy as _copy

    if not old_elements:
        return
    anchor = old_elements[0]
    for el in new_elements:
        anchor.addprevious(_copy.deepcopy(el))
    for el in old_elements:
        el.getparent().remove(el)


def append_elements_before_sectpr(doc: DocumentType, elements: list) -> None:
    """把 elements（外部文档元素，深拷贝）追加到 body 末尾（sectPr 之前）。"""
    import copy as _copy

    sect_pr = doc.element.body.sectPr
    for el in elements:
        if sect_pr is not None:
            sect_pr.addprevious(_copy.deepcopy(el))
        else:
            doc.element.body.append(_copy.deepcopy(el))


def template_has_section(tpl_path: Path, keyword: str) -> bool:
    """动态判断响应模板中是否存在含 keyword 的段落。"""
    if not tpl_path.exists():
        return False
    doc = Document(str(tpl_path))
    return any(keyword in p.text for p in doc.paragraphs)


# —— 无标题样式文档的结构兜底(检测端;重建见 nodes/structure.py)——
_UNSTRUCTURED_MIN_CHARS = 2000   # 体量低于此值不判"结构缺失",避免小样张浪费 LLM 调用
_UNSTRUCTURED_MAX_AVG = 8000     # 有标题但平均节长超此值 => 标题形同虚设


def needs_structure_fallback(sections: list[DocxSection]) -> bool:
    """标题节数过少('明显过少')或平均节长过大('不正确')时需要 LLM 重建结构。"""
    total = sum(len(s.content) for s in sections)
    if total < _UNSTRUCTURED_MIN_CHARS:
        return False
    titled = sum(1 for s in sections if s.level)
    avg = total / max(len(sections), 1)
    return titled < 3 or avg > _UNSTRUCTURED_MAX_AVG


@dataclass
class NumberedBlock:
    """非空内容块的编号视图:prompt 摘要(stub)与切分全文(md)一体两用。"""
    index: int          # 非空块序号,与 LLM prompt 编号一致
    kind: str           # 'p'=段落 | 'table'=表格
    stub: str           # prompt 用一行摘要;表格压成【表格】+首行内容(≤60 字)
    md: str             # 切分用完整内容;段落原文 / 整表管道表格
    element: object | None = None   # body 子元素引用(extract_template 剪裁映射用)
    element_index: int = -1         # 该元素在 body 子元素中的下标(空段也计数)


def iter_numbered_blocks(doc: DocumentType) -> list[NumberedBlock]:
    """按文档顺序产出非空块的编号视图(空段跳过不编号,element_index 按 body 连续计数)。"""
    blocks: list[NumberedBlock] = []
    for el_idx, child in enumerate(doc.element.body.iterchildren()):
        if child.tag == qn("w:p"):
            text = _full_text(Paragraph(child, doc)).strip()
            if not text:
                continue
            blocks.append(NumberedBlock(len(blocks), "p", text, text, child, el_idx))
        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            rows = table.rows
            first = "/".join(
                "\n".join(_full_text(p) for p in c.paragraphs).strip()
                for c in rows[0].cells) if rows else ""
            stub = ("【表格】" + first)[:66]
            blocks.append(NumberedBlock(len(blocks), "table", stub, table_md(table), child, el_idx))
    return blocks


def clip_docx(src: Path, dest: Path, start_index: int, end_index: int) -> None:
    """整包副本删区间:保 [start,end) 与 sectPr,删其余 body 子元素。

    相比"新建文档拷元素",样式/编号定义/页眉页脚随包保留(fill 阶段同哲学);
    end_index 独占;sectPr 固定在 body 尾部,永不删除。
    """
    shutil.copyfile(src, dest)
    doc = Document(str(dest))
    children = list(doc.element.body.iterchildren())
    for i, el in enumerate(children):
        if start_index <= i < end_index or el.tag == qn("w:sectPr"):
            continue
        el.getparent().remove(el)
    doc.save(str(dest))


def find_deviation_tables(doc: DocumentType) -> list[tuple[Table, str]]:
    """定位偏离表:表头任一列含「偏离」字样;按表前标题段落归类。

    kind='contract'(合同条款偏离表)或 'requirement'(采购需求偏离表)。
    真实模板中标题与表格之间常隔「采购代理编号:/包号:」等填充行,故在表前
    最近若干非空段落的窗口内回溯,优先取含「偏离」的标题段判断是否含「合同」。
    """
    found: list[tuple[Table, str]] = []
    recent: list[str] = []
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            if block.text.strip():
                recent.append(block.text.strip())
                del recent[:-4]                      # 只留最近4段(隔开填充行)
        else:
            header = [c.text.strip() for c in block.rows[0].cells] if block.rows else []
            if any("偏离" in h for h in header):
                caption = next((t for t in reversed(recent) if "偏离" in t),
                               recent[-1] if recent else "")
                kind = "contract" if "合同" in caption else "requirement"
                found.append((block, kind))
    return found


def replace_table_rows(table: Table, rows: list[list[str]]) -> None:
    """整表替换数据行:保留表头行与表对象(列宽/表格线/样式),清空其余行后逐行写入。

    单元格按原文档 xlate 语义直接置 text(纯文本,不带格式 run)。
    """
    tbl = table._tbl
    for tr in list(tbl.tr_lst)[1:]:
        tbl.remove(tr)
    for values in rows:
        cells = table.add_row().cells
        for i, val in enumerate(values):
            if i < len(cells):
                cells[i].text = str(val)
