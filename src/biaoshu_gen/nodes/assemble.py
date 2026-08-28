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
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from ..docx_io import (
    adopt_image_rels, append_elements_before_sectpr, copy_docx, docx_block_ranges,
    iter_block_items, markdown_to_docx, replace_elements,
)
from ..state import BidState, run_dir
from .split_template import read_parts_yaml

_TECH_KEYWORDS = ("技术方案", "技术部分", "技术标", "实施方案", "技术")


def _find_range(ranges, keywords: tuple[str, ...]):
    for kw in keywords:
        for r in ranges:
            if kw in r.title:
                return r
    return None


def _body_children_count(path: str | Path) -> int:
    """docx body 顶层子元素数(装配膨胀守卫的切片基准)。"""
    from docx import Document as _Doc

    return len(list(_Doc(str(path)).element.body.iterchildren()))


def _content_elements(md: str) -> list:
    """把 markdown 渲染到临时文档，返回其 body 元素（不含 sectPr）。"""
    scratch = Document()
    markdown_to_docx(scratch, md)
    return [el for el in scratch.element.body.iterchildren()
            if el.tag.split("}")[-1] != "sectPr"]


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
    import copy as _copy

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
    取材:优先该 run 的附加填充产物,其次桶级主产物(仅首 run),否则原始 part——
    整桶单排序键曾致大纲乱序。
    """
    from .split_template import load_entries

    tpl = Path(state.template_docx_path)
    doc = copy_docx(tpl, dest)
    for el in list(doc.element.body.iterchildren()):
        if el.tag != qn("w:sectPr"):
            el.getparent().remove(el)

    extra_all = {**state.extra_products_deviation, **state.extra_products_commercial,
                 **state.extra_products_forms}
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
            if body_injected:                          # 多个 technical run:后续原样保留
                src = part
            else:
                tech = _find_range(docx_block_ranges(part), _TECH_KEYWORDS)
                if tech is not None:
                    replace_elements(tech.elements[1:], _content_elements(body_md))
                else:
                    markdown_to_docx(part, body_md)
                body_injected = True
                src = part
        else:
            src_path = None
            if key in extra_all and Path(extra_all[key]).exists():
                src_path = extra_all[key]              # 该 run 的独立填充产物
            elif key == bucket:
                legacy = getattr(state, f"{bucket}_docx_path", "")
                if legacy and Path(legacy).exists():
                    src_path = legacy                  # 桶级主产物只挂首 run,防重复
            if src_path and Path(src_path).exists():
                # 膨胀守卫:产物元素数远超模板切片(harness 复述了其他章节内容)时弃用——
                # 装配宁用原始 part 也不让幻觉扩写污染草稿
                slice_n = _body_children_count(entry["path"])
                prod_n = _body_children_count(src_path)
                if prod_n > max(3 * slice_n, slice_n + 30):
                    import logging
                    logging.getLogger(__name__).warning(
                        "[assemble] %s 产物 %d 元素远超切片 %d,疑似复述扩写,回退原始 part",
                        key, prod_n, slice_n)
                    src_path = None
            if not (src_path and Path(src_path).exists()):
                src_path = entry["path"]               # 回退原始 part(未填/跳过桶)
            if not (src_path and Path(src_path).exists()):
                continue
            src = Document(str(src_path))
        elements = [el for el in src.element.body.iterchildren()
                    if el.tag != qn("w:sectPr")]
        append_elements_before_sectpr(doc, elements, src_doc=src, img_cache=img_cache)
    if not body_injected and body_md:                  # 无技术桶时 body 兜底尾部追加
        doc.add_page_break()
        markdown_to_docx(doc, "# 技术方案\n\n" + body_md)
    doc.save(str(dest))


def assemble_node(state: BidState) -> dict:
    out_dir = run_dir(state) / "07_draft"
    out_dir.mkdir(parents=True, exist_ok=True)
    version = state.draft_version + 1
    dest = out_dir / f"标书草稿_v{version}.docx"
    body_md = Path(state.body_md_path).read_text(encoding="utf-8")

    manifest = read_parts_yaml(run_dir(state))
    if manifest.get("order") and state.template_docx_path and \
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

    # 技术方案正文 -> 锚定"技术部分"区间（保留锚标题，替换区间其余内容）
    tech = _find_range(docx_block_ranges(doc), _TECH_KEYWORDS)
    if tech is not None:
        replace_elements(tech.elements[1:], _content_elements(body_md))
    else:
        doc.add_page_break()
        markdown_to_docx(doc, "# 技术方案\n\n" + body_md)

    # 商务部分 / 偏离表 -> 同锚区间整段替换；底稿无该区间则仅追加该区间；再兜底整本去重
    from ..fill_context import SECTION_KEYWORDS

    img_cache: dict = {}
    for field, key in (("commercial_docx_path", "commercial"), ("deviation_docx_path", "deviation")):
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
    md_path.write_text(body_md + "\n\n（已并入填充产物：forms / deviation / commercial docx）\n",
                       encoding="utf-8")
    return {"draft_docx_path": str(dest), "draft_md_path": str(md_path), "draft_version": version}
