"""节点 5 v2（rich_body_v2）：与 LLM 交互统一为二级节粒度，返回按三级格式。

与 rich_body（叶子粒度调用）的差异（feedback #76）：
- 媒体需求判定：每个二级节一次调用（UnitMediaNeeds），返回该节全部三级的 needs；
- 正文：每个二级节一次调用（UnitBodies），返回该节全部三级正文，sec_id 对位；
- 表格/图片生成与插入仍按三级小节上下文（沿用 rich_body 的媒体原语）；
- 知识库检索（货物类）：query = 二级标题+描述+其下全部三级标题，整单元共享材料。

不变量：叶子文件（{sec_id}-{标题}.md）仍是落盘单位；body.md 按目录树拼装；
审核回环（body_fix_sections）只写回被点名的小节（同单元其余小节保留盘上原文）。
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import get_settings
from ..fill_context import load_facts
from ..kb_v2 import search_snippets
from ..models import make_agent, run_sync
from ..prompts.rich_body import (
    INSERT_SYSTEM, MEDIA_SYSTEM, build_insert_prompt, build_media_prompt,
)
from ..prompts.rich_body_v2 import (
    UNIT_BODY_SYSTEM, UNIT_PRESET_SYSTEM, build_unit_body_prompt,
    build_unit_preset_prompt,
)
from ..schemas import (
    InsertPoint, Outline, OutlineNode, SectionMedia, UnitBodies, UnitMediaNeeds,
    from_yaml_file, to_yaml_file,
)
from ..state import BidState, run_dir
from .body import _leaf_file, _outline_for_use, _tree_text, assemble_body_md
from .rich_body import (
    _MEDIA_RETRIES, _PRESET_CONCURRENCY, _load_media_needs, _media_file,
    _render_media, _save_media_needs, _validate_media, insert_media_into_content,
    overall_review_leaves,
)


def _units(outline: Outline) -> list[tuple[OutlineNode, list[OutlineNode]]]:
    """二级粒度分组：(二级节点, 其叶子列表)；直挂一级的叶子以一级为界自成一组。"""
    units: list[tuple[OutlineNode, list[OutlineNode]]] = []
    buf: list[OutlineNode] = []
    for ch in outline.sections:
        buf = []
        for sec in ch.children:
            if sec.children:
                if buf:
                    units.append((ch, buf))
                    buf = []
                units.append((sec, sec.leaves()))
            else:
                buf.append(sec)
        if buf:
            units.append((ch, buf))
    return units


def rich_body_v2_node(state: BidState) -> dict:
    outline = _outline_for_use(state)
    d = run_dir(state) / "05_body"
    d.mkdir(parents=True, exist_ok=True)
    leaves = outline.leaves()
    settings = get_settings()

    units = _units(outline)
    # 二级 target_words 实际计算 = 其下叶子之和（正文树上下文展示合计，须在渲染树之前）
    for sec, unit_leaves in units:
        if sec.children:
            sec.target_words = sum(l.target_words for l in unit_leaves)

    # D'：媒体需求判定——每个二级节一次调用，返回该节全部三级的 needs（并发）；
    # 判定只做一次（feedback #77）：结果落盘 media_needs.yaml，回环/续跑用缓存
    needs_cache = _load_media_needs(d)
    for leaf in leaves:
        if leaf.id in needs_cache:
            leaf.media_type = needs_cache[leaf.id]["type"]
            leaf.media_score = needs_cache[leaf.id]["score"]
    preset_agent = make_agent(UnitMediaNeeds, UNIT_PRESET_SYSTEM)

    def preset_unit(sec: OutlineNode, unit_leaves: list[OutlineNode]) -> None:
        pending = [l for l in unit_leaves if l.id not in needs_cache]
        if not pending:
            return
        result: UnitMediaNeeds = run_sync(
            preset_agent, build_unit_preset_prompt(sec, unit_leaves)).output
        by_id = {n.sec_id: n for n in result.needs}
        for leaf in pending:                      # 只应用未缓存叶子（已缓存的保持原判定）
            item = by_id.get(leaf.id)
            if item is None or item.type == "none":
                leaf.media_type, leaf.media_score = None, 0.0
            else:
                leaf.media_type = item.type
                leaf.media_score = min(max(item.score, 0.0), 1.0)
            needs_cache[leaf.id] = {"type": leaf.media_type, "score": leaf.media_score}

    with ThreadPoolExecutor(max_workers=_PRESET_CONCURRENCY) as ex:
        list(ex.map(lambda pair: preset_unit(*pair), units))
    _save_media_needs(d, needs_cache)

    # E：全局控制图/表数量，保留 media_score 高的小节（复用 rich_body 原语）
    overall_review_leaves(outline, {
        "table": settings.media_table_limit,
        "figure": settings.media_figure_limit,
    })
    # 用户编辑优先：03_facts.yaml 存在则以其内容覆盖 state.facts（resume 时不用陈旧值）
    facts = load_facts(state)
    # 检索策略（同 rich_body）：仅货物类检索产品库；query=二级标题+描述+全部三级标题，
    # 一次检索覆盖整单元，单元内叶子共享材料；全部叶子可复用的单元跳过。
    facts.template_fields = {}
    facts.credit_code =""
    facts.legal_person =""
    facts.company_name =""
    facts_text = facts.model_dump_json(indent=2)

    fix_ids = {i for i in (state.body_fix_sections or []) if i in {l.id for l in leaves}}
    is_goods = bool(state.metadata and state.metadata.bid_type == "货物")
    unit_kb_texts: dict[str, str] = {}
    if is_goods:
        for sec, unit_leaves in units:
            if all(l.id not in fix_ids and _leaf_file(d, l).exists() for l in unit_leaves):
                continue
            goods_prefix_query = f"检索 {facts.goods_list} 产品的以下信息：\n"
            query = goods_prefix_query + " ".join(
                [sec.title, sec.description or ""] + [l.title for l in unit_leaves])
            hits = search_snippets(state, query)
            text = "\n\n".join(f"【{name}】\n{text}" for name, text in hits) or "（无）"
            for l in unit_leaves:
                unit_kb_texts[l.id] = text


    # 上下文树：当前单元所在的一级章子树（一级标题 + 其下全部二三级）——正文生成时
    # 让模型看到本章结构定位，又不把整本书塞进每个单元 prompt（全书树在多章大纲下
    # 会随章数线性膨胀）；同一一级下的多个单元共享同一棵树，按节点缓存。
    unit_trees: dict[int, str] = {}

    def _chapter_tree(sec: OutlineNode) -> str:
        key = id(sec)
        if key not in unit_trees:
            ch = next((c for c in outline.sections
                       if c is sec or any(s is sec for s in c.children)), None)
            unit_trees[key] = _tree_text(ch) if ch is not None else _tree_text(sec)
        return unit_trees[key]

    # F'：正文——每个二级节一次调用返回该节全部三级正文（并发=二级单元数闸门）；
    # sec_id 对位写回需要生成的叶子，可复用叶子保留盘上原文
    body_agent = make_agent(UnitBodies, UNIT_BODY_SYSTEM)

    def gen_unit(sec: OutlineNode, unit_leaves: list[OutlineNode]) -> list[tuple[OutlineNode, str]]:
        pending = [l for l in unit_leaves if l.id in fix_ids or not _leaf_file(d, l).exists()]
        if not pending:
            return [(l, _leaf_file(d, l).read_text(encoding="utf-8")) for l in unit_leaves]
        feedback = state.body_feedback if any(l.id in fix_ids for l in unit_leaves) else ""
        result: UnitBodies = run_sync(body_agent, build_unit_body_prompt(
            sec=sec, unit_leaves=unit_leaves, tree=_chapter_tree(sec), facts=facts_text,
            kb=unit_kb_texts.get(unit_leaves[0].id, "（无）"), feedback=feedback,
        )).output
        by_id = {s.sec_id: s for s in result.sections}
        out: list[tuple[OutlineNode, str]] = []
        for leaf in unit_leaves:
            f = _leaf_file(d, leaf)
            if leaf.id in fix_ids or not f.exists():
                content = (by_id.get(leaf.id) or None)
                if content and content.content.strip():
                    f.write_text(content.content, encoding="utf-8")   # 即时落盘
                    out.append((leaf, content.content))
                elif f.exists():            # LLM 漏了该 sec_id：保留盘上原文兜底
                    out.append((leaf, f.read_text(encoding="utf-8")))
                else:
                    out.append((leaf, ""))
            else:
                out.append((leaf, f.read_text(encoding="utf-8")))
        return out

    with ThreadPoolExecutor(max_workers=settings.body_concurrency) as ex:
        results = list(ex.map(lambda pair: gen_unit(*pair), units))
    section_contents = {leaf.id: content for unit in results for leaf, content in unit}
    for leaf in leaves:
        section_contents.setdefault(leaf.id, _leaf_file(d, leaf).read_text(encoding="utf-8"))

    # G：媒体生成与插入——仍按三级小节上下文（沿用 rich_body 原语与媒体文件缓存）
    media_agent = make_agent(SectionMedia, MEDIA_SYSTEM)
    insert_agent = make_agent(InsertPoint, INSERT_SYSTEM)

    def gen_table_or_figure(leaf: OutlineNode) -> tuple[OutlineNode, SectionMedia] | None:
        media_file = _media_file(d, leaf)
        if media_file.exists():
            return leaf, from_yaml_file(SectionMedia, media_file)
        content = section_contents[leaf.id]
        feedback = ""
        for _ in range(_MEDIA_RETRIES + 1):
            result = run_sync(media_agent, build_media_prompt(
                sec_id=leaf.id, title=leaf.title, description=leaf.description,
                media_type=leaf.media_type, content=content, feedback=feedback,
            )).output
            error = _validate_media(result)
            if error is None:
                to_yaml_file(result, media_file)
                return leaf, result
            feedback = error
        return None

    media_leaves = [leaf for leaf in leaves if leaf.media_type]
    with ThreadPoolExecutor(max_workers=_PRESET_CONCURRENCY) as ex:
        media_pairs = [p for p in ex.map(gen_table_or_figure, media_leaves) if p is not None]

    for leaf, media in media_pairs:
        content = section_contents[leaf.id]
        if _render_media(media) in content:
            continue    # 续跑：叶子文件已是插好图表的终版，不重复插入
        section_contents[leaf.id] = insert_media_into_content(content, media, insert_agent)
        _leaf_file(d, leaf).write_text(section_contents[leaf.id], encoding="utf-8")

    # H：整体拼装——按目录树合成全书 body.md
    body_md = assemble_body_md(outline, section_contents, d)
    return {"body_md_path": str(body_md), "body_feedback": "", "body_fix_sections": []}
