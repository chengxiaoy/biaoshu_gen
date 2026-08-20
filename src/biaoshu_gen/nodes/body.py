"""节点 5：按三级小节并发生成技术方案正文；回环时只重生成有问题的小节。"""
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import get_settings
from ..kb import KnowledgeBase
from ..models import make_agent, run_sync
from ..prompts.body import SYSTEM, build_user_prompt
from ..schemas import Outline, OutlineNode, SectionBody, from_yaml_file
from ..state import BidState, run_dir


def _safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "-", title).strip("-")[:40] or "section"


def _outline_for_use(state: BidState) -> Outline:
    """用户编辑优先：04_outline.yaml 存在则覆盖 state.outline（resume 时不用陈旧值）。"""
    yaml_path = run_dir(state) / "04_outline.yaml"
    if yaml_path.exists():
        return from_yaml_file(Outline, yaml_path)
    assert state.outline, "outline 未生成，无法撰写正文"
    return state.outline


def _tree_text(outline: Outline) -> str:
    """全书目录的紧凑渲染（正文 prompt 的上下文）。"""
    lines: list[str] = []

    def walk(node: OutlineNode, depth: int) -> None:
        indent = "  " * depth
        note = f"（约 {node.target_words} 字）" if not node.children and node.target_words else ""
        lines.append(f"{indent}{node.id or '-'} {node.title}{note}")
        for c in node.children:
            walk(c, depth + 1)

    for s in outline.sections:
        walk(s, 0)
    return "\n".join(lines)


def _leaf_file(d: Path, leaf: OutlineNode) -> Path:
    return d / f"{_safe_name(leaf.id or 'sec')}-{_safe_name(leaf.title)}.md"


def body_node(state: BidState) -> dict:
    outline = _outline_for_use(state)
    d = run_dir(state) / "05_body"
    d.mkdir(parents=True, exist_ok=True)
    kb = KnowledgeBase.load(Path(state.kb_dir))
    facts_text = state.facts.model_dump_json(indent=2) if state.facts else ""
    leaves = outline.leaves()

    # 回环修复：只重生成有问题的小节；fix id 在当前目录中不存在（目录被改过）则整体重生成
    leaf_by_id = {l.id: l for l in leaves}
    fix_requested = bool(state.body_fix_sections)
    fix_ids = [i for i in state.body_fix_sections if i in leaf_by_id]
    if fix_requested and not fix_ids:
        targets, reuse_existing = leaves, False        # 目录已改 -> 整体重生成
    elif fix_requested:
        targets, reuse_existing = [leaf_by_id[i] for i in fix_ids], False
    else:
        targets, reuse_existing = leaves, True         # 全新运行：已有叶子文件复用（崩溃续跑）

    tree = _tree_text(outline)
    agent = make_agent(SectionBody, SYSTEM)

    def gen(leaf: OutlineNode) -> tuple[OutlineNode, SectionBody]:
        f = _leaf_file(d, leaf)
        if reuse_existing and f.exists():
            return leaf, SectionBody(title=leaf.title, content=f.read_text(encoding="utf-8"))
        snippets = kb.search(f"{leaf.title} {leaf.description}")
        kb_text = "\n\n".join(f"【{c.source.name}】\n{c.text}" for c in snippets) or "（无）"
        result = run_sync(agent, build_user_prompt(
            sec_id=leaf.id, title=leaf.title, description=leaf.description,
            target_words=leaf.target_words, tree=tree, facts=facts_text, kb=kb_text,
            feedback=state.body_feedback if leaf.id in fix_ids else "",
        )).output
        return leaf, result

    with ThreadPoolExecutor(max_workers=get_settings().body_concurrency) as ex:
        results = list(ex.map(gen, targets))
    for leaf, res in results:
        _leaf_file(d, leaf).write_text(res.content, encoding="utf-8")

    # body.md 由目录树拼装：# 一级 / ## 二级 / ### 三级 + 叶子正文（复用内存中的生成结果，不重读磁盘）
    contents = {leaf.id: res.content for leaf, res in results}
    parts: list[str] = []

    def emit(node: OutlineNode, level: int) -> None:
        heading = "#" * min(level + 1, 4)
        if not node.children:
            content = contents.get(node.id) or _leaf_file(d, node).read_text(encoding="utf-8")
            parts.append(f"{heading} {node.title}\n\n{content}")
        else:
            parts.append(f"{heading} {node.title}")
            for c in node.children:
                emit(c, level + 1)

    for s in outline.sections:
        emit(s, 0)
    body_md = d / "body.md"
    body_md.write_text("\n\n".join(parts), encoding="utf-8")
    return {"body_md_path": str(body_md), "body_feedback": "", "body_fix_sections": []}
