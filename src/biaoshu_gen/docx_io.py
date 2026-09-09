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


_FENCE_RE = re.compile(r"^```(\w*)\s*$")
_HEADING_MD_RE = re.compile(r"^(#{1,4})\s+(.*)$")


def _is_table_sep(s: str) -> bool:
    """markdown 表格分隔行：只含 |:- 与空白，且至少有一个 - 和一个 |。"""
    return bool(s) and set(s) <= set("|:- ") and "-" in s and "|" in s


def _md_blocks(md: str) -> list[tuple]:
    """把 markdown 切成块：('heading', depth, text) / ('table', rows) /
    ('mermaid', code) / ('line', s)。

    围栏优先识别——围栏内行不再按标题/表格/列表解析（mermaid 代码含
    "A-->B" 等任意文本）；分隔行缺失的孤竖线行不算表格，保持段落原样。
    """
    lines = md.splitlines()
    blocks: list[tuple] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        m = _HEADING_MD_RE.match(s)
        if m:
            blocks.append(("heading", len(m.group(1)), m.group(2)))
            i += 1
            continue
        m = _FENCE_RE.match(s)
        if m:
            lang, code_lines = m.group(1).lower(), []
            i += 1
            while i < len(lines) and not _FENCE_RE.match(lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            i += 1                              # 跳过收尾围栏（EOF 缺围栏也接受）
            if lang == "mermaid":
                blocks.append(("mermaid", "\n".join(code_lines).strip()))
            else:
                blocks.extend(("line", ln.strip()) for ln in code_lines if ln.strip())
            continue
        if s.startswith("|") and i + 1 < len(lines) and _is_table_sep(lines[i + 1].strip()):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            rows.pop(1)                         # 分隔行不入表
            blocks.append(("table", rows))
            continue
        blocks.append(("line", s))
        i += 1
    return blocks


def _set_table_borders(table) -> None:
    """表格边框作为直接格式写入（#81）：tblStyle 引用在 styleId 体系不同的
    宿主包（真实模板数字自编号）会悬空，Word 里表格裸奔无边框；直接格式
    随元素跨包搬运，不依赖宿主样式表。"""
    from docx.oxml import OxmlElement

    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")                  # 0.5pt
        el.set(qn("w:color"), "auto")
        borders.append(el)
    # OOXML tblPr 子元素序：tblBorders 在 shd/tblLayout/tblLook 之前
    anchor = next((c for c in tblPr.iterchildren()
                   if c.tag in (qn("w:shd"), qn("w:tblLayout"), qn("w:tblCellMar"),
                                qn("w:tblLook"))), None)
    if anchor is not None:
        anchor.addprevious(borders)
    else:
        tblPr.append(borders)


def _add_md_table(doc: DocumentType, rows: list[list[str]]) -> None:
    """管道表格 → 真 docx 表格（#79）：表头加粗；显式边框（#81）+Table Grid
    样式引用（宿主包有同名样式时叠加格式，缺失不影响边框）。"""
    if not rows:
        return
    cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=cols)
    _set_table_borders(table)
    try:
        table.style = "Table Grid"
    except KeyError:
        pass
    for ri, row in enumerate(rows):
        for ci in range(cols):
            cell = table.cell(ri, ci)
            cell.text = row[ci] if ci < len(row) else ""
            if ri == 0:
                for p in cell.paragraphs:
                    for r in p.runs:
                        r.font.bold = True


_PICTURE_WIDTH_IN = 5.8         # 正文插图目标宽（等比缩放）
_PICTURE_MAX_HEIGHT_IN = 8.0    # 竖版长图按高度封顶（A4/Letter 排版区内），否则 Word 裁掉页外部分


def _add_mermaid(doc: DocumentType, code: str) -> None:
    """mermaid 代码块 → 渲染 PNG 插图（#79）；渲染不可用时降级为代码文本段落。

    默认按宽度等比缩放；图高超出页高时 Word 只显示上半——按高度封顶等比
    缩小，保证全图可见。
    """
    from io import BytesIO

    from docx.shared import Inches

    try:
        from .mermaid_render import render_mermaid_png
        png = render_mermaid_png(code)
    except Exception:                           # 渲染是锦上添花，任何异常都降级
        png = None
    if png:
        shape = doc.add_picture(BytesIO(png), width=Inches(_PICTURE_WIDTH_IN))
        max_h = Inches(_PICTURE_MAX_HEIGHT_IN)
        if shape.height > max_h:
            scale = max_h / shape.height
            shape.height = int(shape.height * scale)
            shape.width = int(shape.width * scale)
        return
    for ln in code.splitlines():
        if ln.strip():
            doc.add_paragraph(ln)


_HEADING_STYLE_NAME_RE = re.compile(r"^(?:Heading|标题)\s*(\d)$", re.IGNORECASE)


def _find_style_by_id(doc: DocumentType, style_id: str):
    for s in doc.styles:
        if s.style_id == style_id:
            return s
    return None


def _style_outline_level(style) -> int | None:
    """样式定义内声明的大纲级别（w:style/w:pPr/w:outlineLvl，0-based）。"""
    pPr = style.element.find(qn("w:pPr"))
    if pPr is None:
        return None
    el = pPr.find(qn("w:outlineLvl"))
    try:
        return int(el.get(qn("w:val"))) if el is not None else None
    except (TypeError, ValueError):
        return None


def _map_style_id(old_id: str, src_doc: DocumentType, dest_doc: DocumentType,
                  kind: str) -> str | None:
    """把 src 包 styleId 语义对位到 dest 包：返回 None 表示保持原值。

    ①dest 已认识该 id（模板自带/fill 产物同族）→ 不动最稳；②解析名相同；
    ③Heading N/标题 N 按大纲级别对位宿主标题样式（仅段落样式，真实标书
    模板标题体系 styleId 常是数字自编号，run-20260908-215413 实测）。
    """
    if _find_style_by_id(dest_doc, old_id) is not None:
        return None
    src_style = _find_style_by_id(src_doc, old_id)
    if src_style is None:
        return None
    name = src_style.name
    try:
        return dest_doc.styles[name].style_id
    except KeyError:
        pass
    if kind == "p":
        m = _HEADING_STYLE_NAME_RE.match(name or "")
        if m:
            want = int(m.group(1)) - 1
            from docx.enum.style import WD_STYLE_TYPE

            cands = [s for s in dest_doc.styles
                     if s.type == WD_STYLE_TYPE.PARAGRAPH
                     and _style_outline_level(s) == want]
            if len(cands) == 1:
                return cands[0].style_id
            named = [s for s in cands
                     if re.search(r"标题|heading", s.name or "", re.IGNORECASE)]
            if named:
                return named[0].style_id
    return None


def retarget_style_ids(elements: list, src_doc: DocumentType,
                       dest_doc: DocumentType) -> None:
    """跨包搬运前把元素引用的 pStyle/tblStyle 重定到宿主包 styleId（#81 续）。

    scratch 渲染产物的样式引用（Heading1/TableGrid）在 styleId 体系不同的
    宿主标书模板里解析不到——标题塌成正文格式、表格丢样式。按样式语义
    （解析名/大纲级别）动态读取宿主样式表对位，映射不到保持原值。
    """
    cache: dict[tuple[str, str], str | None] = {}
    for el in elements:
        for node in el.iter():
            if node.tag == qn("w:pStyle"):
                kind, old = "p", node.get(qn("w:val"))
            elif node.tag == qn("w:tblStyle"):
                kind, old = "tbl", node.get(qn("w:val"))
            else:
                continue
            if not old:
                continue
            key = (kind, old)
            if key not in cache:
                cache[key] = _map_style_id(old, src_doc, dest_doc, kind)
            if cache[key]:
                node.set(qn("w:val"), cache[key])


# 合成兜底标题样式的级别字号（半磅）：H1 16pt / H2 14pt / H3 13pt / H4 12pt
_FALLBACK_HEADING_SIZE_HP = {1: 32, 2: 28, 3: 26, 4: 24}


def ensure_style_fallbacks(elements: list, src_doc: DocumentType,
                           dest_doc: DocumentType) -> None:
    """retarget 后仍悬空的标题引用：在宿主 styles.xml 合成最小标题样式兜底。

    宿主既无同名样式也无级别对位样式时（探测不到的最后一层），按悬空 id
    合成段落样式——加粗 + 级别字号 + outlineLvl，字体继承模板默认（中文标书
    观感），标题不再以正文外观显示。悬空 id 本就是宿主空闲 id，无冲突。
    """
    from docx.oxml import OxmlElement

    dangling: dict[str, tuple[str, int]] = {}       # styleId -> (样式名, 级别)
    for el in elements:
        if not el.tag == qn("w:p"):
            continue
        pPr = el.find(qn("w:pPr"))
        if pPr is None:
            continue
        p_style = pPr.find(qn("w:pStyle"))
        if p_style is None:
            continue
        val = p_style.get(qn("w:val"))
        if not val or _find_style_by_id(dest_doc, val) is not None or val in dangling:
            continue
        src_style = _find_style_by_id(src_doc, val)
        name = (src_style.name if src_style is not None else None) or val
        level = None
        outline = pPr.find(qn("w:outlineLvl"))      # 段落直写级别优先
        if outline is not None:
            try:
                level = int(outline.get(qn("w:val"))) + 1
            except (TypeError, ValueError):
                level = None
        if level is None and src_style is not None:  # 回退:源样式定义内的级别
            src_lvl = _style_outline_level(src_style)
            level = src_lvl + 1 if src_lvl is not None else None
        if level is None:
            continue
        dangling[val] = (name, level)
    styles_el = dest_doc.styles.element
    for val, (name, level) in dangling.items():
        style = OxmlElement("w:style")
        style.set(qn("w:type"), "paragraph")
        style.set(qn("w:styleId"), val)
        style_name = OxmlElement("w:name")
        style_name.set(qn("w:val"), name)
        style.append(style_name)
        style.append(OxmlElement("w:qFormat"))
        pPr = OxmlElement("w:pPr")
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), str(level - 1))
        pPr.append(outline)
        style.append(pPr)
        rPr = OxmlElement("w:rPr")
        rPr.append(OxmlElement("w:b"))
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(_FALLBACK_HEADING_SIZE_HP.get(level, 24)))
        rPr.append(sz)
        style.append(rPr)
        styles_el.append(style)


def _set_outline_level(para, level: int) -> None:
    """直接写段落大纲级别 w:outlineLvl(0-based,#80 通用解法)。

    真实标书模板的 styleId 常是数字自编号,注入段落的 pStyle(如 Heading4)在
    宿主包解析不到会塌回 Normal——级别写在段落属性上,不依赖 pStyle 能否解析,
    Word 导航窗格/目录照常识别。
    """
    from docx.oxml import OxmlElement

    pPr = para._p.get_or_add_pPr()
    el = pPr.find(qn("w:outlineLvl"))
    if el is None:
        el = OxmlElement("w:outlineLvl")
        anchor = next((c for c in pPr.iterchildren()
                       if c.tag in (qn("w:rPr"), qn("w:sectPr"), qn("w:pPrChange"))), None)
        if anchor is not None:
            anchor.addprevious(el)              # OOXML pPr 子元素序:outlineLvl 靠后
        else:
            pPr.append(el)
    el.set(qn("w:val"), str(min(level - 1, 8)))


def number_headings(md: str) -> str:
    """给 markdown 标题加章节号（#80）：#→"1. 标题"、##→"1.1 标题"、
    ###→"1.1.1 标题"——同级递增、升级清零,编号深度恒等于标题层级。

    锚点只决定注入落点,不改变编号(按锚降级曾致编号 1.1.1.1 爆炸,
    run-20260908-215413 实证)。围栏内行跳过;非标题行原样保留。
    """
    counters = [0] * 5
    out: list[str] = []
    in_fence = False
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        m = _HEADING_MD_RE.match(s)
        if not m:
            out.append(line)
            continue
        depth = len(m.group(1))
        counters[depth] += 1
        for i in range(depth + 1, 5):
            counters[i] = 0
        segs = [str(counters[i]) for i in range(1, depth + 1)]
        number = ".".join(segs) + ("." if len(segs) == 1 else "")
        out.append(f"{'#' * depth} {number} {m.group(2).strip()}")
    return "\n".join(out)


def markdown_to_docx(doc: DocumentType, md: str, heading_offset: int = 0) -> None:
    """极量版 Markdown → docx：标题/列表/段落/表格/mermaid 渲染插图。

    heading_offset:标题整体降级偏移(仅渲染层能力;assemble 注入不再降级,
    级别由 outlineLvl 直写保证)。
    """
    for block in _md_blocks(md):
        if block[0] == "heading":
            level = max(1, min(4, block[1] + heading_offset))
            try:
                para = doc.add_heading(block[2], level=level)
            except KeyError:                    # 模板缺 Heading N 样式时回退
                para = doc.add_paragraph(block[2])
            _set_outline_level(para, level)
        elif block[0] == "table":
            _add_md_table(doc, block[1])
        elif block[0] == "mermaid":
            _add_mermaid(doc, block[1])
        else:
            s = block[1]
            if s.startswith(("- ", "* ")):
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


def body_children_count(doc_or_path: "DocumentType | Path | str") -> int:
    """docx body 顶层子元素数(不含 sectPr)——切片规模与膨胀守卫的统一度量。"""
    doc = doc_or_path if hasattr(doc_or_path, "element") else Document(str(doc_or_path))
    return len([el for el in doc.element.body.iterchildren()
                if not el.tag.endswith("}sectPr")])


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


def replace_elements(old_elements: list, new_elements: list, *,
                     dest_doc: DocumentType | None = None,
                     src_doc: DocumentType | None = None,
                     img_cache: dict | None = None) -> None:
    """就地替换：new_elements（来自其他文档，自动深拷贝）替换 old_elements，保持原位置。

    传 dest_doc+src_doc 时先为新元素迁移图片关系——跨文档搬运的内建步骤，
    调用方无需（也不应）单独手工调用 adopt_image_rels。
    """
    import copy as _copy

    if not old_elements:
        return
    if dest_doc is not None and src_doc is not None:
        adopt_image_rels(dest_doc, src_doc, new_elements, img_cache)
    anchor = old_elements[0]
    for el in new_elements:
        anchor.addprevious(_copy.deepcopy(el))
    for el in old_elements:
        el.getparent().remove(el)


def append_elements_before_sectpr(doc: DocumentType, elements: list, *,
                                  src_doc: DocumentType | None = None,
                                  img_cache: dict | None = None) -> None:
    """把 elements（外部文档元素，深拷贝）追加到 body 末尾（sectPr 之前）。

    传 src_doc 时先迁移图片关系(同 replace_elements)。
    """
    import copy as _copy

    if src_doc is not None:
        adopt_image_rels(doc, src_doc, elements, img_cache)
    sect_pr = doc.element.body.sectPr
    for el in elements:
        if sect_pr is not None:
            sect_pr.addprevious(_copy.deepcopy(el))
        else:
            doc.element.body.append(_copy.deepcopy(el))


def adopt_image_rels(dest_doc: DocumentType, src_doc: DocumentType,
                     elements: list, cache: dict | None = None) -> None:
    """跨文档搬运前迁移图片关系：把 elements 引用 src_doc 包内图片的 rId
    改写为 dest_doc 新注册的 rId（图片部件按 blob 注册，包级按 SHA1 去重）。

    不迁移则 a:blip@r:embed / v:imagedata@r:id 仍指源文档关系表——Word 打开
    显示空白，而 inline_shapes 计数照常（只数 XML 节点不解析关系）。
    """
    from io import BytesIO

    if cache is None:
        cache = {}
    _vml_imagedata = "{urn:schemas-microsoft-com:vml}imagedata"   # nsmap 无 v 前缀
    for el in elements:
        for node in el.iter():
            if node.tag == qn("a:blip"):
                attr = qn("r:embed")
            elif node.tag == _vml_imagedata:
                attr = qn("r:id")
            else:
                continue
            old = node.get(attr)
            if not old:
                continue
            if old in cache:
                node.set(attr, cache[old])
                continue
            try:
                blob = src_doc.part.rels[old].target_part.blob
            except KeyError:
                continue                           # 源文档无此关系,保持原样
            new_rid, _ = dest_doc.part.get_or_add_image(BytesIO(blob))
            cache[old] = new_rid
            node.set(attr, new_rid)


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
    """定位偏离表:表头任一列含「偏离」字样,返回 (表格, 表标题)。

    表标题支持任意形态(合同条款/采购需求/技术/商务偏离表等):取表前最近4个
    非空段落窗口内含「偏离」的标题段(真实模板中标题与表格之间常隔
    「采购代理编号:/包号:」等填充行);无则退化为最近一段,再无则空串。
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
                found.append((block, caption))
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


def clip_docx_keep(src: Path, dest: Path, keep_indexes: list[int]) -> None:
    """整包副本多区间保留:只留 keep_indexes 中的 body 子元素(sectPr 永留),其余删除。

    与 clip_docx 同族(保样式/编号定义/页眉页脚),用于把模板按 bucket 物理拆分。
    """
    import shutil as _shutil

    _shutil.copyfile(src, dest)
    doc = Document(str(dest))
    keep = set(keep_indexes)
    for i, el in enumerate(doc.element.body.iterchildren()):
        if i in keep or el.tag == qn("w:sectPr"):
            continue
        el.getparent().remove(el)
    doc.save(str(dest))
