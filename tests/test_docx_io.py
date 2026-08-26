from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from biaoshu_gen.docx_io import (
    DocxSection, copy_docx, docx_to_markdown, docx_to_sections, markdown_to_docx,
    needs_structure_fallback,
)


def _make_tender_docx(path: Path) -> None:
    doc = Document()
    doc.add_heading("第一章 招标公告", level=1)
    doc.add_paragraph("项目名称：测试项目")
    t = doc.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "名称"
    t.cell(0, 1).text = "数量"
    t.cell(1, 0).text = "应用软件 A"
    t.cell(1, 1).text = "1 套"
    doc.save(path)


def test_docx_to_markdown_keeps_order_and_table(tmp_path: Path):
    p = tmp_path / "t.docx"
    _make_tender_docx(p)
    md = docx_to_markdown(p)
    assert "# 第一章 招标公告" in md
    assert "项目名称：测试项目" in md
    assert "| 名称 | 数量 |" in md
    assert "| 应用软件 A | 1 套 |" in md
    assert md.index("招标公告") < md.index("项目名称") < md.index("应用软件 A")


def test_docx_to_sections_splits_by_heading(tmp_path: Path):
    p = tmp_path / "t2.docx"
    doc = Document()
    doc.add_paragraph("抬头说明")                      # 首个标题前 → 前言
    doc.add_heading("第一章 招标公告", level=1)
    doc.add_paragraph("项目名称：测试项目")
    doc.add_heading("评标办法", level=1)
    doc.add_paragraph("最低价得 100 分")
    doc.save(p)
    secs = docx_to_sections(p)
    assert [(s.level, s.title) for s in secs] == [
        (0, "(前言)"), (1, "第一章 招标公告"), (1, "评标办法")]
    assert "抬头说明" in secs[0].content
    assert "项目名称" in secs[1].content
    assert "100 分" in secs[2].content


def test_markdown_to_docx_headings_and_list(tmp_path: Path):
    doc = Document()
    markdown_to_docx(doc, "# 总体方案\n\n本章说明总体设计。\n\n- 要点一\n- 要点二\n")
    paras = [p.text for p in doc.paragraphs]
    styles = [p.style.name for p in doc.paragraphs]
    assert "总体方案" in paras and "本章说明总体设计。" in paras and "要点一" in paras
    assert any("Heading 1" in s for s in styles)
    assert any("List" in s for s in styles)




def test_copy_docx(tmp_path: Path):
    src = tmp_path / "tpl.docx"
    _make_tender_docx(src)
    doc = copy_docx(src, tmp_path / "tpl_copy.docx")
    assert "第一章 招标公告" in "\n".join(p.text for p in doc.paragraphs)
    assert (tmp_path / "tpl_copy.docx").exists()


def test_markdown_to_docx_style_fallback():
    """中文模板底稿常缺 List Bullet 等样式：样式缺失时回退普通段落，不崩溃。"""
    doc = Document()
    for name in ("List Bullet", "List Number", "Heading 2"):
        el = doc.styles[name].element
        el.getparent().remove(el)
    markdown_to_docx(doc, "## 某标题\n\n- 要点一\n\n1. 步骤一\n")
    texts = [p.text for p in doc.paragraphs]
    assert "要点一" in texts and "步骤一" in texts and "某标题" in texts


def test_template_has_section(tmp_path: Path):
    from biaoshu_gen.docx_io import template_has_section

    no = tmp_path / "no.docx"
    d = Document()
    d.add_paragraph("投标函")
    d.save(no)
    assert template_has_section(no, "偏离") is False

    yes = tmp_path / "yes.docx"
    d = Document()
    d.add_paragraph("偏离表")
    d.save(yes)
    assert template_has_section(yes, "偏离") is True
    assert template_has_section(tmp_path / "missing.docx", "偏离") is False


def _big_unstructured_docx(path: Path) -> None:
    """零 Heading 样式的大文档(模拟'不标准格式'招标文件)。"""
    doc = Document()
    doc.add_paragraph("第一章 采购需求")            # 普通段落,非 Heading 样式
    doc.add_paragraph("本系统需支持不少于 1000 并发。" * 80)   # ~1600 字
    doc.add_paragraph("第二章 评标办法")
    doc.add_paragraph("价格分采用低价优先法计算。" * 80)
    doc.save(path)


def test_needs_structure_fallback_triggers_on_no_heading(tmp_path: Path):
    p = tmp_path / "bad.docx"
    _big_unstructured_docx(p)
    assert needs_structure_fallback(docx_to_sections(p)) is True


def test_needs_structure_fallback_skips_small_docs(tmp_path: Path):
    """体量不足 _UNSTRUCTURED_MIN_CHARS 的文档不触发(避免小样张浪费 LLM 调用)。"""
    p = tmp_path / "small.docx"
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("项目名称:测试项目")
    doc.save(p)
    assert needs_structure_fallback(docx_to_sections(p)) is False


def test_needs_structure_fallback_triggers_on_huge_avg_section():
    """有标题但平均节长超限('不正确')也触发。

    构造保证只命中 avg 分支:titled=3(不满足 titled<3),
    每节 '正文九千字。'×1500=9000 字,total=27000≥2000,avg=9000>8000。
    """
    from biaoshu_gen.docx_io import DocxSection as DS
    direct = [DS(1, f"第{i}章 说明", "正文九千字。" * 1500)   # 单节 9000 字
              for i in range(1, 4)]
    assert needs_structure_fallback(direct) is True


def test_needs_structure_fallback_false_for_healthy_docs():
    healthy = [DocxSection(1, f"第{i}章 说明", "内容。" * 200) for i in range(1, 7)]
    assert needs_structure_fallback(healthy) is False


def test_iter_numbered_blocks_numbers_and_stubs_tables():
    from biaoshu_gen.docx_io import iter_numbered_blocks

    doc = Document()
    doc.add_paragraph("")                                # 空段跳过
    doc.add_paragraph("第一章 采购需求")
    t = doc.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "名称"
    t.cell(0, 1).text = "数量"
    t.cell(1, 0).text = "应用软件 A"
    t.cell(1, 1).text = "1 套"
    doc.add_paragraph("以上设备须为全新原装。")

    blocks = iter_numbered_blocks(doc)
    assert [(b.index, b.kind) for b in blocks] == [(0, "p"), (1, "table"), (2, "p")]
    assert blocks[0].stub == "第一章 采购需求"
    assert "【表格】" in blocks[1].stub and "名称" in blocks[1].stub
    assert "| 名称 | 数量 |" in blocks[1].md and "| 应用软件 A | 1 套 |" in blocks[1].md
    assert blocks[2].md == "以上设备须为全新原装。"


def _add_ins_text(container_para_or_cell_para, text: str) -> None:
    ins = OxmlElement("w:ins")
    ins.set(qn("w:id"), "1")
    ins.set(qn("w:author"), "测试")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    r.append(t)
    ins.append(r)
    container_para_or_cell_para._p.append(ins)


def test_w_ins_revision_text_is_extracted(tmp_path: Path):
    """带修订插入标记的段落与表格文字必须可抽取(样本评分表全在此形态)。"""
    p = tmp_path / "rev.docx"
    doc = Document()
    doc.add_paragraph("第一章 评审因素和标准")           # 普通段落标题
    body = doc.add_paragraph()
    _add_ins_text(body, "报价部分满分 50 分。")          # 正文在 w:ins 内
    tbl = doc.add_table(rows=1, cols=1)
    _add_ins_text(tbl.cell(0, 0).paragraphs[0], "技术部分 38 分")
    doc.save(p)

    secs = docx_to_sections(p)
    assert "报价部分满分 50 分。" in secs[-1].content
    assert "| 技术部分 38 分 |" in secs[-1].content      # 管道表格按整表拼接,w:ins 文字在内
    md = docx_to_markdown(p)
    assert "技术部分 38 分" in md and "| 技术" in md      # 单元格内 w:ins 文字进表格


def test_iter_numbered_blocks_extracts_w_ins_text():
    """结构兜底路径依赖 stub/md:修订标记(w:ins)文字必须进段落块与表格 stub。"""
    from biaoshu_gen.docx_io import iter_numbered_blocks

    doc = Document()
    blank = doc.add_paragraph()                           # w:ins 全空 -> 空段仍跳过
    _add_ins_text(blank, "")
    body = doc.add_paragraph()
    _add_ins_text(body, "报价部分满分 50 分。")            # 段落正文全在 w:ins 内
    tbl = doc.add_table(rows=1, cols=1)
    _add_ins_text(tbl.cell(0, 0).paragraphs[0], "技术部分 38 分")

    blocks = iter_numbered_blocks(doc)
    assert [(b.index, b.kind) for b in blocks] == [(0, "p"), (1, "table")]   # 空 w:ins 不占号
    assert "报价部分满分 50 分。" in blocks[0].stub
    assert blocks[0].md == "报价部分满分 50 分。"
    assert "技术部分 38 分" in blocks[1].stub             # 表格 stub 首行摘要下钻 w:ins


def test_iter_numbered_blocks_records_element_index():
    from biaoshu_gen.docx_io import iter_numbered_blocks

    doc = Document()
    doc.add_paragraph("")                        # 空段:跳过不编号,但 body 下标仍占位
    doc.add_paragraph("第一章 采购需求")
    t = doc.add_table(rows=1, cols=1)
    t.cell(0, 0).text = "报价表"

    blocks = iter_numbered_blocks(doc)
    children = list(doc.element.body.iterchildren())
    assert [(b.index, b.kind) for b in blocks] == [(0, "p"), (1, "table")]
    assert blocks[0].element_index == 1          # 空段占位 0,计数不回退
    assert blocks[0].element is children[1]
    assert blocks[1].element_index == 2 and blocks[1].element is children[2]


def test_clip_docx_keeps_range_and_sectpr(tmp_path: Path):
    from biaoshu_gen.docx_io import clip_docx, iter_numbered_blocks

    src = tmp_path / "t.docx"
    doc = Document()
    doc.add_paragraph("第二章 投标人须知")
    doc.add_paragraph("须知正文。")
    doc.add_paragraph("第七章 投标文件的格式")
    doc.add_paragraph("投标函格式正文。")
    doc.save(src)

    probe = Document(str(src))
    blocks = iter_numbered_blocks(probe)
    start = next(b.element_index for b in blocks if b.stub.startswith("第七章"))
    end = len(list(probe.element.body.iterchildren()))

    dest = tmp_path / "tpl.docx"
    clip_docx(src, dest, start, end)
    out = Document(str(dest))
    texts = [p.text for p in out.paragraphs]
    assert any("投标文件的格式" in x for x in texts)
    assert any("投标函" in x for x in texts)
    assert not any("投标人须知" in x for x in texts)
    assert out.element.body.sectPr is not None


def test_clip_docx_excludes_end_boundary(tmp_path: Path):
    """end_index 指向的元素本身不属于模板(独占)。"""
    from biaoshu_gen.docx_io import clip_docx, iter_numbered_blocks

    src = tmp_path / "t.docx"
    doc = Document()
    doc.add_paragraph("第七章 投标文件的格式")
    doc.add_paragraph("投标函格式正文。")
    doc.add_paragraph("第八章 其他事项")
    doc.save(src)

    probe = Document(str(src))
    blocks = iter_numbered_blocks(probe)
    start = next(b.element_index for b in blocks if b.stub.startswith("第七章"))
    end = next(b.element_index for b in blocks if b.stub.startswith("第八章"))

    dest = tmp_path / "tpl.docx"
    clip_docx(src, dest, start, end)
    texts = [p.text for p in Document(str(dest)).paragraphs]
    assert any("投标函" in x for x in texts)
    assert not any("第八章" in x for x in texts)


def _deviation_doc(path):
    """两块偏离表样本:标题与表格之间隔填充行(采购代理编号/包号),复现真实模板结构。"""
    from docx import Document

    doc = Document()
    doc.add_paragraph("七、合同条款偏离表")
    doc.add_paragraph("采购代理编号：")
    doc.add_paragraph("包号：")
    t1 = doc.add_table(rows=2, cols=5)
    for i, h in enumerate(["序号", "磋商文件章节条款号", "磋商文件要求", "响应文件的应答", "偏离说明"]):
        t1.cell(0, i).text = h
    t1.cell(1, 0).text = ""
    doc.add_paragraph("八、采购需求偏离表")
    doc.add_paragraph("采购代理编号：")
    doc.add_paragraph("包号：")
    t2 = doc.add_table(rows=3, cols=5)
    for i, h in enumerate(["序号", "磋商文件章节条款号", "磋商文件要求", "响应文件应答", "偏离说明"]):
        t2.cell(0, i).text = h
    doc.add_table(rows=2, cols=3).cell(0, 0).text = "无关表"      # 非偏离表
    doc.save(path)
    return doc


def test_find_deviation_tables_classifies_by_caption(tmp_path: Path):
    from biaoshu_gen.docx_io import find_deviation_tables

    p = tmp_path / "tpl.docx"
    _deviation_doc(p)
    found = find_deviation_tables(Document(str(p)))
    assert [kind for _, kind in found] == ["contract", "requirement"]
    assert len({id(t) for t, _ in found}) == 2                     # 两张不同的表


def test_replace_table_rows_keeps_header_and_writes_rows(tmp_path: Path):
    from biaoshu_gen.docx_io import find_deviation_tables, replace_table_rows

    p = tmp_path / "tpl.docx"
    _deviation_doc(p)
    doc = Document(str(p))
    table, kind = find_deviation_tables(doc)[0]
    assert kind == "contract"
    replace_table_rows(table, [["1", "第12条", "交货期30天", "承诺30天交货", "无偏离"],
                               ["2", "第15条", "质保期3年", "满足", "正偏离"]])
    doc.save(p)
    out = Document(str(p))
    t = find_deviation_tables(out)[0][0]
    assert [c.text for c in t.rows[0].cells][:2] == ["序号", "磋商文件章节条款号"]   # 表头保留
    assert len(t.rows) == 3                                        # 1表头+2数据行,旧空行已清
    assert [c.text for c in t.rows[1].cells] == ["1", "第12条", "交货期30天", "承诺30天交货", "无偏离"]
    assert t.rows[2].cells[4].text == "正偏离"
