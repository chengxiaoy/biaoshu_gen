from biaoshu_gen.docx_io import DocxSection, NumberedBlock
from biaoshu_gen.nodes import structure as st
from biaoshu_gen.schemas import StructureHeading, StructureOutline


def _block(i: int, text: str) -> NumberedBlock:
    return NumberedBlock(index=i, kind="p", stub=text, md=text)


def test_validate_headings_drops_bad_and_clamps():
    outline = StructureOutline.model_validate({"headings": [
        {"index": 3, "level": 1, "title": "第三章 评标办法"},
        {"index": 1, "level": 1, "title": "第一章 总体要求"},      # 乱序 -> 丢弃
        {"index": 5, "level": 9, "title": "第五章 附则"},          # level 夹取 3
        {"index": 7, "level": 2, "title": ""},                     # 空 title 丢弃
        {"index": 8, "level": 2, "title": "x" * 51},               # 超 50 字丢弃
        {"index": 9, "level": 0, "title": "第六章 其他"},          # level 夹取 1
    ]})
    hs = st.validate_headings(outline, n_blocks=12)
    assert [(h.index, h.level, h.title) for h in hs] == [
        (3, 1, "第三章 评标办法"), (5, 3, "第五章 附则"), (9, 1, "第六章 其他")]
    assert hs[0].index == 3                                        # 幸存者首位强制 level 1 已是 1


def test_split_by_headings_assigns_content_and_preamble():
    blocks = [_block(i, t) for i, t in enumerate([
        "封面文字", "第一章 总体要求", "系统需支持 1000 并发。",
        "1.1 性能指标", "响应时间 ≤ 2 秒。", "第二章 商务条款", "质保三年。",
    ])]
    headings = [StructureHeading(index=1, level=1, title="第一章 总体要求"),
                StructureHeading(index=3, level=3, title="1.1 性能指标"),
                StructureHeading(index=5, level=1, title="第二章 商务条款")]
    secs = st.split_by_headings(blocks, headings)
    assert [(s.level, s.title) for s in secs] == [
        (0, "(前言)"), (1, "第一章 总体要求"), (3, "1.1 性能指标"), (1, "第二章 商务条款")]
    assert secs[0].content == "封面文字"
    assert "1000 并发" in secs[1].content
    assert "响应时间" in secs[2].content
    assert "质保三年" in secs[3].content


def test_split_by_headings_drops_empty_preamble():
    blocks = [_block(i, t) for i, t in enumerate(["第一章 总则", "正文若干。"])]
    secs = st.split_by_headings(blocks, [StructureHeading(index=0, level=1, title="第一章 总则")])
    assert [(s.level, s.title) for s in secs] == [(1, "第一章 总则")]
