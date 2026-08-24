"""无标题样式文档的结构重建:LLM 定界 + 代码校验 + 本地切分(设计见 specs/2026-08-24)。"""
from pathlib import Path

from docx import Document

from biaoshu_gen.docx_io import DocxSection, NumberedBlock
from biaoshu_gen.schemas import StructureHeading, StructureOutline

from ..docx_io import iter_numbered_blocks
from ..models import make_agent, run_sync       # noqa: F401  (测试 monkeypatch st.make_agent)
from ..prompts.structure import SYSTEM, build_user_prompt

_MAX_TITLE = 50


class StructureError(RuntimeError):
    """结构重建失败(LLM 两次输出均未通过校验)。"""


def validate_headings(outline: StructureOutline, n_blocks: int) -> list[StructureHeading]:
    """代码侧硬校验:乱序/越界 index 与非法 title 丢弃,level 夹取 1~3,幸存首位强制 1 级。"""
    out: list[StructureHeading] = []
    last = -1
    for h in outline.headings:
        if not (0 <= h.index < n_blocks) or h.index <= last:
            continue
        title = h.title.strip()
        if not title or len(title) > _MAX_TITLE:
            continue
        level = min(max(h.level, 1), 3)
        if not out:
            level = 1
        out.append(StructureHeading(index=h.index, level=level, title=title))
        last = h.index
    return out


def split_by_headings(blocks: list[NumberedBlock],
                      headings: list[StructureHeading]) -> list[DocxSection]:
    """按标题边界本地切分:内容取自原块 md,LLM 只决定归属。"""
    bounds = {h.index: h for h in headings}
    secs: list[DocxSection] = []
    cur = DocxSection(0, "(前言)", "")

    def flush():
        nonlocal cur
        if cur.content or cur.level:
            secs.append(cur)

    for b in blocks:
        h = bounds.get(b.index)
        if h is not None:
            flush()
            cur = DocxSection(h.level, h.title, "")
        cur.content = (cur.content + "\n\n" + b.md).strip()
    flush()
    return secs


_RETRY_TIMES = 2   # 首次 + 校验失败重试一次


def rebuild_sections(path: Path) -> list[DocxSection]:
    """无标题样式文档的结构重建:块化 -> 单次 LLM 定界 -> 硬校验(失败带错重试一次)-> 本地切分。"""
    blocks = iter_numbered_blocks(Document(str(path)))
    blocks_text = "\n".join(f"[{b.index}] {b.stub}" for b in blocks)
    agent = make_agent(StructureOutline, SYSTEM)

    prompt = build_user_prompt(blocks_text)
    headings: list[StructureHeading] = []
    err = "未得到任何有效标题"
    for _ in range(_RETRY_TIMES):
        outline: StructureOutline = run_sync(agent, prompt).output
        headings = validate_headings(outline, n_blocks=len(blocks))
        if headings:
            break
        prompt = build_user_prompt(blocks_text) + f"\n\n上一次输出未通过校验(错误:{err}),请修正后重新输出。"
    if not headings:
        raise StructureError(f"结构重建失败:文档 {path} 两次输出均无有效标题(最后错误:{err})")
    return split_by_headings(blocks, headings)
