"""节点 5（rich 版）：正文并发生成 + 表格/mermaid 图按需生成插入。

流程（设计文档《硬件/服务类标书智能体方案设计》图表生成流程）：
AI 判定各小节图表需求 -> 全局数量控制 -> 并发生成正文 -> 生成图表并插入合适位置
-> 按目录拼装落盘。与 body_node 同参同回，可整体替换 05 节点。
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re

from ..config import get_settings
from ..kb_v2 import search_snippets
from ..mermaid_render import render_check
from ..models import make_agent, run_sync
from ..prompts.body import SYSTEM as BODY_SYSTEM, build_user_prompt as build_body_prompt
from ..prompts.rich_body import (
    INSERT_SYSTEM, MEDIA_SYSTEM, PRESET_SYSTEM,
    build_insert_prompt, build_media_prompt, build_preset_prompt,
)
from ..schemas import (
    InsertPoint, MediaNeed, Outline, OutlineNode, SectionBody, SectionMedia,
    from_yaml_file, to_yaml_file,
)
from ..state import BidState, run_dir
from .body import _leaf_file, _outline_for_use, _safe_name, _tree_text, assemble_body_md

_PRESET_CONCURRENCY = 5   # 需求判定与媒体生成并发上限（设计文档：信号量 5）
_MEDIA_RETRIES = 1        # 校验失败带错误反馈重试次数；仍失败则该节放弃图表（降级）

# mermaid 合法图型关键字（首词校验，挡住 LLM 输出的解释性文字/代码围栏误判）
_MERMAID_HEADS = {
    "flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram",
    "erDiagram", "gantt", "pie", "mindmap", "timeline", "journey", "quadrantChart",
    "requirementDiagram", "gitGraph", "sankey", "architecture", "C4Context",
}


def rich_body_node(state: BidState) -> dict:
    outline = _outline_for_use(state)
    d = run_dir(state) / "05_body"
    d.mkdir(parents=True, exist_ok=True)
    leaves = outline.leaves()
    settings = get_settings()

    # D：AI 判定各小节 mermaid 图/表需求（并发，信号量 5）——判定只做一次（feedback #77）：
    # 结果落盘 media_needs.yaml，review 回环/续跑重入时直接用缓存，不再触发判定
    needs_cache = _load_media_needs(d)
    for leaf in leaves:
        if leaf.id in needs_cache:
            leaf.media_type = needs_cache[leaf.id]["type"]
            leaf.media_score = needs_cache[leaf.id]["score"]
    pending_leaves = [n for n in leaves if n.id not in needs_cache]
    if pending_leaves:
        preset_agent = make_agent(MediaNeed, PRESET_SYSTEM)
        with ThreadPoolExecutor(max_workers=_PRESET_CONCURRENCY) as ex:
            list(ex.map(lambda n: preset_table_figure(n, preset_agent), pending_leaves))
        for n in pending_leaves:
            needs_cache[n.id] = {"type": n.media_type, "score": n.media_score}
        _save_media_needs(d, needs_cache)

    # E：全局控制图/表数量，保留 media_score 高的小节
    overall_review_leaves(outline, {
        "table": settings.media_table_limit,
        "figure": settings.media_figure_limit,
    })

    # F：正文生成——按二级目录粒度并发（同一二级下的叶子串行，保持章内衔接）；
    # 崩溃续跑：叶子文件已存在则复用；审核回环（body_fix_sections）强制重生成问题小节
    facts_text = state.facts.model_dump_json(indent=2) if state.facts else ""

    def _units() -> list[tuple[OutlineNode, list[OutlineNode]]]:
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

    units = _units()
    # 二级 target_words 实际计算 = 其下叶子之和（正文树上下文展示合计，须在渲染树之前）
    for sec, unit_leaves in units:
        if sec.children:
            sec.target_words = sum(l.target_words for l in unit_leaves)

    tree = _tree_text(outline)
    body_agent = make_agent(SectionBody, BODY_SYSTEM)
    fix_ids = {i for i in (state.body_fix_sections or []) if i in {l.id for l in leaves}}

    # 检索策略（feedback #76/#77）：仅货物类标书检索产品知识库；query = 二级标题+描述+
    # 其下全部三级标题（一次检索覆盖整个二级单元），单元内叶子共享同一份材料；
    # 非货物类（服务/工程）企业信息走 facts 记账，正文不参考知识库。
    # 只对"确有生成需求"的单元检索（全部叶子可复用的单元跳过）。
    is_goods = bool(state.metadata and state.metadata.bid_type == "货物")
    unit_kb_texts: dict[str, str] = {}
    if is_goods:
        for sec, unit_leaves in units:
            if all(l.id not in fix_ids and _leaf_file(d, l).exists() for l in unit_leaves):
                continue
            query = " ".join(
                [sec.title, sec.description or ""] + [l.title for l in unit_leaves])
            hits = search_snippets(state, query)
            text = "\n\n".join(f"【{name}】\n{text}" for name, text in hits) or "（无）"
            for l in unit_leaves:
                unit_kb_texts[l.id] = text

    def gen_content(leaf: OutlineNode) -> tuple[OutlineNode, SectionBody]:
        """根据 outline node 生成 SectionBody。"""
        f = _leaf_file(d, leaf)
        if f.exists() and leaf.id not in fix_ids:
            return leaf, SectionBody(title=leaf.title, content=f.read_text(encoding="utf-8"))
        kb_text = unit_kb_texts.get(leaf.id, "（无）")
        feedback = state.body_feedback if leaf.id in fix_ids else ""
        result = run_sync(body_agent, build_body_prompt(
            sec_id=leaf.id, title=leaf.title, description=leaf.description,
            target_words=leaf.target_words, tree=tree, facts=facts_text, kb=kb_text,
            feedback=feedback,
        )).output
        f.write_text(result.content, encoding="utf-8")   # 即时落盘：中断后重跑只需补缺
        return leaf, result

    todo_leaves = [l for l in leaves if l.id in fix_ids or not _leaf_file(d, l).exists()]
    with ThreadPoolExecutor(max_workers=settings.body_concurrency) as ex:
        results = list(ex.map(gen_content, todo_leaves))
    section_contents = {leaf.id: body.content for leaf, body in results}
    # 复用的叶子不在 todo 里，从磁盘补齐内容
    for leaf in leaves:
        section_contents.setdefault(leaf.id, _leaf_file(d, leaf).read_text(encoding="utf-8"))

    # G：为带图表需求的小节生成图/表，插入到正文的合适位置
    media_agent = make_agent(SectionMedia, MEDIA_SYSTEM)
    insert_agent = make_agent(InsertPoint, INSERT_SYSTEM)

    def gen_table_or_figure(leaf: OutlineNode) -> tuple[OutlineNode, SectionMedia] | None:
        """根据 outline node 生成 SectionMedia（table 为 Markdown，figure 为经校验的 mermaid）。

        已有媒体文件直接复用；校验不过带反馈重试一次，仍不过返回 None（该节降级为纯文字）。
        """
        media_file = _media_file(d, leaf)
        if media_file.exists():
            return leaf, from_yaml_file(SectionMedia, media_file)
        content = section_contents[leaf.id]
        kb_text = unit_kb_texts.get(leaf.id, "（无）")
        feedback = ""
        for _ in range(_MEDIA_RETRIES + 1):
            result = run_sync(media_agent, build_media_prompt(
                sec_id=leaf.id, title=leaf.title, description=leaf.description,
                media_type=leaf.media_type, content=content, kb=kb_text, feedback=feedback,
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
        _leaf_file(d, leaf).write_text(section_contents[leaf.id], encoding="utf-8")  # 回写终版章节 md

    # H：整体拼装——按目录树合成全书 body.md
    body_md = assemble_body_md(outline, section_contents, d)
    return {"body_md_path": str(body_md), "body_feedback": "", "body_fix_sections": []}


def _media_file(d: Path, leaf: OutlineNode) -> Path:
    return d / f"{_safe_name(leaf.id or 'sec')}-{_safe_name(leaf.title)}.media.yaml"


def _load_media_needs(d: Path) -> dict[str, dict]:
    """读取已落盘的图表需求判定缓存 {sec_id: {type, score}}（无缓存返回空）。"""
    import yaml

    p = d / "media_needs.yaml"
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {k: {"type": v.get("type"), "score": float(v.get("score") or 0.0)}
            for k, v in data.items()}


def _save_media_needs(d: Path, needs: dict[str, dict]) -> None:
    import yaml

    (d / "media_needs.yaml").write_text(
        yaml.safe_dump(needs, allow_unicode=True, sort_keys=True), encoding="utf-8")


def preset_table_figure(node: OutlineNode, agent) -> None:
    """使用 LLM 判定当前叶子 outline node 是否需要图表，填充 media_type 和 media_score。

    判定为不需要时置 None / 0 分（后续全局限额即不再考虑该小节）。
    """
    result: MediaNeed = run_sync(agent, build_preset_prompt(
        sec_id=node.id, title=node.title, description=node.description,
        target_words=node.target_words,
    )).output
    if result.type == "none":
        node.media_type, node.media_score = None, 0.0
    else:
        node.media_type = result.type
        node.media_score = min(max(result.score, 0.0), 1.0)


def overall_review_leaves(root: Outline, media_limit: dict[str, int]) -> None:
    """根据总的图表数量限制，控制含图表小节的数量，原则上保留 media_score 较高的小节。"""
    leaves = root.leaves()
    for typ, cap in media_limit.items():
        group = sorted(
            (n for n in leaves if n.media_type == typ),
            key=lambda n: n.media_score, reverse=True,
        )
        for n in group[cap:]:
            n.media_type, n.media_score = None, 0.0


def insert_media_into_content(content: str, media: SectionMedia, agent, delimiter: str = "\n") -> str:
    """使用 LLM 根据正文内容和媒体类型，判断媒体插入到分隔符划分的合适位置。

    为节省 token 和确保正确性，LLM 只需返回第几个分隔符（插入到第 index 段之前），
    后续程序拼接在一起后返回整体内容；越界位置收敛到 [0, 段数]。
    """
    paragraphs = content.split(delimiter)
    result: InsertPoint = run_sync(agent, build_insert_prompt(
        paragraphs=paragraphs, media_type=media.type or "table",
        caption=media.media_caption or "",
    )).output
    idx = min(max(result.index, 0), len(paragraphs))
    paragraphs.insert(idx, _render_media(media))
    return delimiter.join(paragraphs)


def _render_media(media: SectionMedia) -> str:
    """媒体块渲染：figure 用 mermaid 代码围栏，table 直接 Markdown；题注显式
    带 图：/表： 前缀（assemble 渲染层据此自动编号「图N./表N.」并居中，#82）。"""
    if media.type == "figure":
        body = f"```mermaid\n{_strip_mermaid_fence(media.media_content)}\n```"
        cap = f"图：{(media.media_caption or '').strip()}"
    else:
        body = media.media_content.strip()
        cap = f"表：{(media.media_caption or '').strip()}"
    return f"{body}\n\n{cap}"


def _strip_mermaid_fence(text: str) -> str:
    """LLM 常把 mermaid 代码包在 ``` 围栏里，剥掉后再入块（块本身自带围栏）。"""
    m = re.match(r"^```(?:mermaid)?\s*\n(.*?)\n?```\s*$", text.strip(), re.S)
    return (m.group(1) if m else text).strip()


def _validate_media(media: SectionMedia) -> str | None:
    """媒体校验：table 查表头分隔行；figure 先做结构检查，再交 mmdc 真实渲染。

    渲染器缺失/环境不可用时自动跳过渲染检查（结构检查兜底）。
    返回错误说明（作为重试反馈），合法返回 None。
    """
    if not (media.media_caption or "").strip():
        return "media_caption 不能为空"
    text = (media.media_content or "").strip()
    if media.type == "figure":
        code = _strip_mermaid_fence(text)
        head = code.split(maxsplit=1)[0] if code else ""
        if head not in _MERMAID_HEADS:
            return f"mermaid 代码需以 flowchart/sequenceDiagram 等图型关键字开头，当前开头为 {head!r}"
        for open_c, close_c in (("(", ")"), ("[", "]"), ("{", "}")):
            if code.count(open_c) != code.count(close_c):
                return f"mermaid 代码中括号 {open_c}{close_c} 不配对"
        render_error = render_check(code)
        if render_error:
            return f"mermaid 渲染失败：{render_error}"
    else:
        lines = [l for l in text.splitlines() if l.strip()]
        if len(lines) < 2 or "|" not in lines[0] or not re.search(r":?-{2,}", lines[1]):
            return "表格需为 Markdown 格式：首行表头含 |，第二行为 |---|---| 分隔行"
    return None
