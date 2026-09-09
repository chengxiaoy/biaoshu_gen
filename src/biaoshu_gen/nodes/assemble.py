"""节点 10：拼装标书草稿 docx（纯代码，无 LLM）。

主路径（parts.yaml 存在，四分拆后）：**顺序拼接**——以整模板为样式壳清空 body，
按 parts.yaml 的文档原序并入各桶：technical 用原始 part 作容器注入 body，
其余桶取填充产物（跳过的桶用原始 part），part 即精确切分天然无重复。

回退路径（老 run 无 parts.yaml）：**标题锚定的分段替换**——
- 底稿 = forms.docx（模板壳 + 已填的投标函/报价/资格）> 标书模板.docx > 新建；
- 技术方案正文：写入底稿"技术部分/技术方案"锚点区间（找不到锚点才追加尾部）；
- 商务部分/偏离表：在底稿与填充文档中按锚标题定位**同一区间**，整段替换（空壳 → 已填），
  规避逐块文本去重在"同节不同填充状态"下的重复拼接与误删；
- 底稿没有对应区间时，仅把填充文档中**该区间的内容**追加尾部（不整本拼接）；
- 填充文档连锚标题都没有时，兜底走整本去重追加。
"""
import copy as _copy
import logging
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from ..docx_io import (
    adopt_image_rels, append_elements_before_sectpr, body_children_count, copy_docx,
    docx_block_ranges, ensure_style_fallbacks, iter_block_items, markdown_to_docx,
    number_headings, replace_elements, retarget_style_ids,
)
from ..state import BidState, run_dir
from .split_template import load_entries, read_parts_yaml

log = logging.getLogger(__name__)

_TECH_KEYWORDS = ("技术方案", "技术部分", "技术标", "实施方案", "技术")
# 膨胀守卫阈值(2026-08-28 实证:flash 把 3 元素章节封面扩成 441 元素整章)
_BLOAT_RATIO = 3
_BLOAT_MARGIN = 30


def _find_range(ranges, keywords: tuple[str, ...]):
    for kw in keywords:
        for r in ranges:
            if kw in r.title:
                return r
    return None


def _inject_technical_body(container: Document, body_md: str,
                           img_cache: dict | None = None) -> bool:
    """把技术正文注入宿主容器:找到技术锚区间则整段替换。层级按锚挂接
    (锚 H4 时正文 #→H4/##→H5/###→H6),编号与层级解耦、恒为 1./1.1/1.1.1
    (#80 的编号要求 + #83 的位置要求:导航/目录嵌在宿主「技术部分>技术方案」
    之下,不横插顶层章节);大纲级别经 w:outlineLvl 直写保证;标题/表格样式
    对位宿主样式表,插图关系随搬运迁移。找不到锚返回 False。"""
    tech = _find_range(docx_block_ranges(container), _TECH_KEYWORDS)
    if tech is None:
        return False
    offset = max(tech.level - 1, 0)
    scratch, elements = _content_elements(number_headings(body_md),
                                          heading_offset=offset)
    retarget_style_ids(elements, scratch, container)   # 标题/表格样式对位宿主样式表
    ensure_style_fallbacks(elements, scratch, container)   # 仍悬空的标题合成兜底样式
    if len(tech.elements) > 1:
        replace_elements(tech.elements[1:], elements, dest_doc=container,
                         src_doc=scratch, img_cache=img_cache)
    else:
        # 锚即区间尾(切片只有标题、无内容元素):replace_elements 对空区间是
        # no-op,正文会整体静默丢失——改为插在锚标题之后
        adopt_image_rels(container, scratch, elements, img_cache)
        anchor = tech.elements[0]
        for el in reversed(elements):
            anchor.addnext(_copy.deepcopy(el))
    return True


def _content_elements(md: str, heading_offset: int = 0) -> tuple[Document, list]:
    """把 markdown 渲染到临时文档，返回 (scratch 文档, body 元素不含 sectPr)。

    heading_offset:层级按宿主锚点挂接(#83)。返回 scratch 是为了搬运后把其中
    插图(mermaid 渲染 PNG)的关系迁入宿主包,否则 Word 显示空白。
    """
    scratch = Document()
    markdown_to_docx(scratch, md, heading_offset=heading_offset)
    elements = [el for el in scratch.element.body.iterchildren()
                if el.tag.split("}")[-1] != "sectPr"]
    return scratch, elements


def _block_key(block) -> str:
    """段落取全文，表格取全部单元格文本，用于兜底去重比较。"""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    if isinstance(block, Paragraph):
        return f"p:{block.text.strip()}"
    if isinstance(block, Table):
        return "t:" + "|".join(c.text.strip() for row in block.rows for c in row.cells)
    return ""


def _collect_keys(doc: Document) -> set:
    return {key for block in iter_block_items(doc) if (key := _block_key(block))}


def _append_docx_dedup(dest: Document, src: Document, existing: set,
                       img_cache: dict | None = None) -> None:
    """兜底：整本去重追加（src 中与底稿文本相同的块跳过）。

    逐块先筛选再搬运,无法走内建迁移的 mover,此处手工配对 adopt(注释即契约)。"""
    if img_cache is None:
        img_cache = {}
    sect_pr = dest.element.body.sectPr
    for block in iter_block_items(src):
        key = _block_key(block)
        if not key or key in existing:
            continue
        existing.add(key)
        el = block._element
        adopt_image_rels(dest, src, [el], img_cache)   # 迁移插图关系后深拷贝
        el = _copy.deepcopy(el)
        if sect_pr is not None:
            sect_pr.addprevious(el)
        else:
            dest.element.body.append(el)


def _assemble_from_parts(state: BidState, manifest: dict, dest: Path, body_md: str) -> None:
    """主路径：整模板样式壳清空 body，按 entries(run 粒度,文档原序)拼接。

    同桶多区间(sources 如 (四)(五) 商务段嵌在投标函与资格之间)以 run 为单位
    取材:优先该 run 的附加填充产物,其次桶级主产物(仅 primary run),否则原始
    part——整桶单排序键曾致大纲乱序。
    """
    tpl = Path(state.template_docx_path)
    doc = copy_docx(tpl, dest)
    for el in list(doc.element.body.iterchildren()):
        if el.tag != qn("w:sectPr"):
            el.getparent().remove(el)

    extra_all = state.extra_products or {}
    img_cache: dict = {}                              # 包级图片去重:各条目共享
    body_injected = False
    for entry in load_entries(manifest):
        bucket = entry["bucket"]
        key = entry["key"]
        if bucket == "technical":
            container = entry["path"]
            if not (container and Path(container).exists()):
                continue
            part = Document(str(container))            # 技术部分以原始 part 为容器
            if not body_injected and _inject_technical_body(part, body_md, img_cache):
                body_injected = True
            src = part                                 # 多 technical run 后续原样保留
        else:
            src_doc = None
            candidate = extra_all.get(key) if extra_all else None
            if not candidate and entry.get("primary"):
                candidate = getattr(state, f"{bucket}_docx_path", "")   # 桶级产物只挂首 run
            if candidate and Path(candidate).exists():
                # 膨胀守卫:产物元素数远超模板切片(harness 复述了其他章节内容)时弃用——
                # 装配宁用原始 part 也不让幻觉扩写污染草稿;开一次文档同时计数与取材
                prod = Document(str(candidate))
                slice_n = body_children_count(entry["path"])
                prod_n = body_children_count(prod)
                if prod_n > max(_BLOAT_RATIO * slice_n, slice_n + _BLOAT_MARGIN):
                    log.warning("[assemble] %s 产物 %d 元素远超切片 %d,疑似复述扩写,回退原始 part",
                                key, prod_n, slice_n)
                else:
                    src_doc = prod
            if src_doc is None:
                src_path = entry["path"]               # 回退原始 part(未填/跳过桶/被守卫拒绝)
                if not Path(src_path).exists():
                    continue
                src_doc = Document(str(src_path))
            src = src_doc
        elements = [el for el in src.element.body.iterchildren()
                    if el.tag != qn("w:sectPr")]
        retarget_style_ids(elements, src, doc)     # 进壳一跳:样式对位宿主样式表
        ensure_style_fallbacks(elements, src, doc)
        append_elements_before_sectpr(doc, elements, src_doc=src, img_cache=img_cache)
    if not body_injected and body_md:                  # 无技术桶时 body 兜底尾部追加
        doc.add_page_break()
        prefix = "" if body_md.lstrip().startswith("#") else "# 技术方案\n\n"
        markdown_to_docx(doc, number_headings(prefix + body_md))
    doc.save(str(dest))


def assemble_node(state: BidState) -> dict:
    out_dir = run_dir(state) / "07_draft"
    out_dir.mkdir(parents=True, exist_ok=True)
    version = state.draft_version + 1
    dest = out_dir / f"标书草稿_v{version}.docx"
    body_md = Path(state.body_md_path).read_text(encoding="utf-8")

    manifest = read_parts_yaml(run_dir(state))
    if (manifest.get("entries") or manifest.get("order")) and state.template_docx_path and \
            Path(state.template_docx_path).exists():
        _assemble_from_parts(state, manifest, dest, body_md)
        return _finish(state, dest, out_dir, version, body_md)

    # 回退路径：底稿 = 填好的 forms 优先（避免空模板壳），否则响应模板，否则新建
    if state.forms_docx_path and Path(state.forms_docx_path).exists():
        doc = copy_docx(Path(state.forms_docx_path), dest)
    elif state.template_docx_path and Path(state.template_docx_path).exists():
        doc = copy_docx(Path(state.template_docx_path), dest)
    else:
        doc = Document()
        if state.metadata and state.metadata.project_name:
            doc.add_heading(f"{state.metadata.project_name} 投标文件", level=0)

    # 技术方案正文 -> 锚定"技术部分"区间(命中锚按锚层级降级注入;未命中追加尾部)
    img_cache: dict = {}
    if not _inject_technical_body(doc, body_md, img_cache):
        doc.add_page_break()
        prefix = "" if body_md.lstrip().startswith("#") else "# 技术方案\n\n"
        markdown_to_docx(doc, number_headings(prefix + body_md))

    # 偏离表 -> 同锚区间整段替换；底稿无该区间则仅追加该区间；再兜底整本去重
    # （商务/表单内容已并入 forms.docx 底稿，不再单独替换）
    from ..fill_context import SECTION_KEYWORDS

    for field, key in (("deviation_docx_path", "deviation"),):
        path = getattr(state, field)
        if not (path and Path(path).exists()):
            continue
        src = Document(str(path))
        keywords = SECTION_KEYWORDS[key]
        src_range = _find_range(docx_block_ranges(src), keywords)
        base_range = _find_range(docx_block_ranges(doc), keywords)
        if src_range is not None and base_range is not None:
            replace_elements(base_range.elements, src_range.elements,
                             dest_doc=doc, src_doc=src, img_cache=img_cache)
        elif src_range is not None:
            doc.add_page_break()
            append_elements_before_sectpr(doc, src_range.elements,
                                          src_doc=src, img_cache=img_cache)
        else:
            doc.add_page_break()
            _append_docx_dedup(doc, src, _collect_keys(doc), img_cache)
    doc.save(str(dest))
    return _finish(state, dest, out_dir, version, body_md)


def _finish(state: BidState, dest: Path, out_dir: Path, version: int, body_md: str) -> dict:
    (out_dir / "latest.txt").write_text(str(version), encoding="utf-8")
    md_path = out_dir / f"标书草稿_v{version}.md"
    md_path.write_text(body_md + "\n\n（已并入填充产物：forms / deviation docx）\n",
                       encoding="utf-8")
    return {"draft_docx_path": str(dest), "draft_md_path": str(md_path), "draft_version": version}
