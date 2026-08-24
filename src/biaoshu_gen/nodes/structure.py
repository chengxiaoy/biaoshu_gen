"""无标题样式文档的结构重建:LLM 定界 + 代码校验 + 本地切分(设计见 specs/2026-08-24)。"""
from biaoshu_gen.docx_io import DocxSection, NumberedBlock
from biaoshu_gen.schemas import StructureHeading, StructureOutline

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
