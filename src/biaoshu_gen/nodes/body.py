"""body 阶段共享工具（原 body 节点已由 rich_body 替换——见 nodes/rich_body.py）。

本模块保留 rich_body / body_review 共用的目录与落盘原语：
_safe_name / _outline_for_use / _tree_text / _leaf_file / assemble_body_md。
"""
import re
from pathlib import Path

from ..schemas import Outline, OutlineNode, from_yaml_file
from ..state import BidState, run_dir


def _safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "-", title).strip("-")[:40] or "section"


def _outline_for_use(state: BidState) -> Outline:
    """用户编辑优先：04_outline.yaml 存在则覆盖 state.outline（resume 时不用陈旧值）。"""
    yaml_path = run_dir(state) / "04_outline.yaml"
    if yaml_path.exists():
        state.outline = from_yaml_file(Outline, yaml_path)

    assert state.outline, "outline 未生成，无法撰写正文"
    return state.outline


def _tree_text(outline: Outline) -> str:
    """全书目录的紧凑渲染（正文 prompt 的上下文）。"""
    lines: list[str] = []

    def walk(node: OutlineNode, depth: int) -> None:
        indent = "  " * depth
        # 二级节的 target_words 是其下叶子之和（rich_body 实际计算），一并展示
        note = f"（约 {node.target_words} 字）" if node.target_words else ""
        lines.append(f"{indent}{node.id or '-'} {node.title}{note}")
        for c in node.children:
            walk(c, depth + 1)

    for s in outline.sections:
        walk(s, 0)
    return "\n".join(lines)


def _leaf_file(d: Path, leaf: OutlineNode) -> Path:
    return d / f"{_safe_name(leaf.id or 'sec')}-{_safe_name(leaf.title)}.md"


def assemble_body_md(outline: Outline, contents: dict[str, str], d: Path) -> Path:
    """按目录树拼装 body.md：# 一级 / ## 二级 / ### 三级 + 叶子正文。

    内存结果优先；小节 id 缺失（异常情况）回读对应叶子文件兜底。供 rich_body 使用。
    """
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
    return body_md
