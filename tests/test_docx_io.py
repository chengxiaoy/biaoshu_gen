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


_MIN_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def test_markdown_table_becomes_docx_table():
    """#79:正文管道表格须渲染为真 docx 表格,不能落为竖线纯文本段落。"""
    markdown_to_docx(doc := Document(),
                     "# 系统功能\n\n| 功能 | 描述 |\n|---|---|\n"
                     "| 统一认证 | 单点登录 |\n| 监测告警 | 阈值触发 |\n\n正文说明。")
    assert len(doc.tables) == 1
    t = doc.tables[0]
    assert [c.text for c in t.rows[0].cells] == ["功能", "描述"]
    assert [c.text for c in t.rows[1].cells] == ["统一认证", "单点登录"]
    assert t.rows[2].cells[1].text == "阈值触发"
    texts = [p.text for p in doc.paragraphs]
    assert not any("|" in x for x in texts)            # 管道行不再进段落
    assert "正文说明。" in texts and "系统功能" in texts


def test_markdown_table_without_separator_stays_text():
    """孤竖线行(无 |---| 分隔行)不是表格,保持原样为段落,不误建表。"""
    doc = Document()
    markdown_to_docx(doc, "| 孤行 | 不是表格 |\n")
    assert len(doc.tables) == 0
    assert [p.text for p in doc.paragraphs] == ["| 孤行 | 不是表格 |"]


def test_markdown_mermaid_renders_picture(monkeypatch):
    """#79:mermaid 围栏须经渲染器出图并 add_picture 入文档,代码不再落为段落。"""
    import biaoshu_gen.mermaid_render as mr

    monkeypatch.setattr(mr, "render_mermaid_png", lambda code: _MIN_PNG)
    doc = Document()
    markdown_to_docx(doc, "# 流程\n\n```mermaid\nflowchart LR\n  A-->B\n```\n\n图：总体流程\n")
    assert len(doc.inline_shapes) == 1
    blip = next(doc.element.body.iter(qn("a:blip")))
    rid = blip.get(qn("r:embed"))
    assert doc.part.rels[rid].target_part.blob == _MIN_PNG     # 图片字节已入包
    texts = [p.text for p in doc.paragraphs]
    assert not any("flowchart" in x for x in texts)            # 代码文本不再出现
    assert "图1. 总体流程" in texts                             # 图题保留并自动编号


def test_markdown_mermaid_degrades_to_code_text(monkeypatch):
    """渲染环境不可用(返回 None)时降级为代码文本段落,内容不丢、不崩溃。"""
    import biaoshu_gen.mermaid_render as mr

    monkeypatch.setattr(mr, "render_mermaid_png", lambda code: None)
    doc = Document()
    markdown_to_docx(doc, "```mermaid\nflowchart LR\n  A-->B\n```\n")
    assert len(doc.inline_shapes) == 0
    assert any("flowchart LR" in x.text for x in doc.paragraphs)


def test_adopt_image_rels_cache_keyed_by_content_not_source_rid():
    """#88:共享 img_cache 跨源文档时,同号 rId 不同图不得串图——assemble 中
    forms 桶先入的 rId16(身份证扫描件)曾使 technical part 同号 rId16(mermaid
    渲染图)缓存命中,1.2.2 流程图被整体改写成身份证图。cache 须按图片内容
    (SHA1)去重;同内容跨文档仍应复用同一 rId(包级去重语义保留)。"""
    from io import BytesIO

    from biaoshu_gen.docx_io import append_elements_before_sectpr

    png_a = _MIN_PNG
    png_b = _MIN_PNG.replace(b"\x05\x00\x01", b"\x06\x00\x01")   # 换 IDAT 像素字节
    assert png_a != png_b

    def _pic_el(doc):
        for el in doc.element.body.iterchildren():
            if any(n.tag == qn("a:blip") for n in el.iter()):
                return el
        raise AssertionError("文档中没有图片段落")

    src_forms, src_tech = Document(), Document()
    src_forms.add_picture(BytesIO(png_a))     # 两个 fresh doc 的下一空闲 rId 同号
    src_tech.add_picture(BytesIO(png_b))      # (均为 rId9),复现跨文档撞号

    dest = Document()
    cache: dict = {}                          # assemble 全程共享的 img_cache
    append_elements_before_sectpr(dest, [_pic_el(src_forms)],
                                   src_doc=src_forms, img_cache=cache)
    append_elements_before_sectpr(dest, [_pic_el(src_tech)],
                                   src_doc=src_tech, img_cache=cache)

    rids = [b.get(qn("r:embed")) for b in dest.element.body.iter(qn("a:blip"))]
    assert rids[0] != rids[1]                 # 不同图不得串到同一个 rId
    assert {dest.part.rels[r].target_part.blob for r in rids} == {png_a, png_b}

    src_dup = Document()                      # 第三文档同内容图:按 SHA1 复用
    src_dup.add_picture(BytesIO(png_a))
    append_elements_before_sectpr(dest, [_pic_el(src_dup)],
                                   src_doc=src_dup, img_cache=cache)
    rids = [b.get(qn("r:embed")) for b in dest.element.body.iter(qn("a:blip"))]
    assert rids[-1] == rids[0]                # 同内容跨文档仍去重为同一 rId

    # 两跳链(assemble 真实形态): scratch -> 中转 part -> 终稿 dest。
    # 第一跳把图注册进 part 的 rId16,若缓存值不辨 dest,第二跳会把 part 的
    # rId16 当成 dest 的 rId16 填回去——dest 里同号关系是另一张图即串图。
    part = Document()                         # 中转容器(rels 空闲号与 dest 无关)
    part.add_paragraph("锚")
    scratch = Document()
    scratch.add_picture(BytesIO(png_b))
    append_elements_before_sectpr(part, [_pic_el(scratch)],
                                  src_doc=scratch, img_cache=cache)   # hop1
    final = Document()
    part_els = [_pic_el(part)]
    append_elements_before_sectpr(final, part_els, src_doc=part,
                                   img_cache=cache)                    # hop2
    rid = [b.get(qn("r:embed")) for b in final.element.body.iter(qn("a:blip"))][0]
    assert final.part.rels[rid].target_part.blob == png_b   # 内容跟着走,不串图


def test_number_headings_three_levels():
    """#80:三级目录加章节号——#→1. / ##→1.1 / ###→1.1.1,同级递增、升级清零。"""
    from biaoshu_gen.docx_io import number_headings

    md = ("# 总体方案\n\n正文。\n\n## 实施要点\n\n### 进度安排\n\n- 要点\n\n"
          "## 保障措施\n\n# 应急预案\n")
    out = number_headings(md)
    assert "# 1. 总体方案" in out
    assert "## 1.1 实施要点" in out
    assert "### 1.1.1 进度安排" in out
    assert "## 1.2 保障措施" in out
    assert "# 2. 应急预案" in out
    assert "正文。" in out and "- 要点" in out          # 非标题行原样保留


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


def test_find_deviation_tables_returns_captions(tmp_path: Path):
    from biaoshu_gen.docx_io import find_deviation_tables

    p = tmp_path / "tpl.docx"
    _deviation_doc(p)
    found = find_deviation_tables(Document(str(p)))
    assert [cap for _, cap in found] == ["七、合同条款偏离表", "八、采购需求偏离表"]
    assert len({id(t) for t, _ in found}) == 2                     # 两张不同的表


def test_replace_table_rows_keeps_header_and_writes_rows(tmp_path: Path):
    from biaoshu_gen.docx_io import find_deviation_tables, replace_table_rows

    p = tmp_path / "tpl.docx"
    _deviation_doc(p)
    doc = Document(str(p))
    table, caption = find_deviation_tables(doc)[0]
    assert caption == "七、合同条款偏离表"
    replace_table_rows(table, [["1", "第12条", "交货期30天", "承诺30天交货", "无偏离"],
                               ["2", "第15条", "质保期3年", "满足", "正偏离"]])
    doc.save(p)
    out = Document(str(p))
    t = find_deviation_tables(out)[0][0]
    assert [c.text for c in t.rows[0].cells][:2] == ["序号", "磋商文件章节条款号"]   # 表头保留
    assert len(t.rows) == 3                                        # 1表头+2数据行,旧空行已清
    assert [c.text for c in t.rows[1].cells] == ["1", "第12条", "交货期30天", "承诺30天交货", "无偏离"]
    assert t.rows[2].cells[4].text == "正偏离"


def test_clip_docx_keep_multiple_ranges(tmp_path: Path):
    """多区间保留:区间外全删,sectPr 永留,区间内段落原样。"""
    from biaoshu_gen.docx_io import clip_docx_keep, iter_numbered_blocks

    src = tmp_path / "t.docx"
    doc = Document()
    for text in ("第五章 响应文件组成", "一、磋商响应声明", "六、项目实施方案",
                 "七、合同条款偏离表", "八、采购需求偏离表", "十二、最后报价"):
        doc.add_paragraph(text)
    doc.save(src)

    probe = Document(str(src))
    blocks = iter_numbered_blocks(probe)
    idx = {b.stub: b.element_index for b in blocks}
    keep = sorted([idx["七、合同条款偏离表"], idx["八、采购需求偏离表"],   # 偏离 bucket
                   idx["一、磋商响应声明"]])                              # forms bucket

    dest = tmp_path / "part.docx"
    clip_docx_keep(src, dest, keep)
    texts = [p.text for p in Document(str(dest)).paragraphs]
    assert texts == ["一、磋商响应声明", "七、合同条款偏离表", "八、采购需求偏离表"]
    assert Document(str(dest)).element.body.sectPr is not None


def test_markdown_table_has_explicit_borders():
    """#81:表格样式不能只靠 tblStyle 引用——真实模板 styleId 体系不同(数字
    自编号)会让 TableGrid 引用悬空,Word 里表格无边框。边框须作为直接格式
    (w:tblBorders)写进表格,随元素跨包搬运,不依赖宿主包样式表。"""
    from docx.oxml.ns import qn

    doc = Document()
    markdown_to_docx(doc, "| a | b |\n|---|---|\n| 1 | 2 |\n")
    tblPr = doc.tables[0]._tbl.tblPr
    borders = tblPr.find(qn("w:tblBorders"))
    assert borders is not None, "缺 w:tblBorders 直接格式"
    edges = {c.tag.split("}")[-1] for c in borders}
    assert {"top", "left", "bottom", "right", "insideH", "insideV"} <= edges


def test_retarget_style_ids_maps_by_name_to_host_id():
    """#81 续:scratch 样式引用(Heading1)在 styleId 体系不同的宿主包解析不到——
    标题塌成正文格式。搬运前须按解析名对位宿主 styleId(真实模板实测:
    标题样式名 Heading 1,styleId 却是 '2')。"""
    import copy as _copy

    from biaoshu_gen.docx_io import retarget_style_ids

    dest = Document()
    dest.add_heading("宿主", level=1)
    dest.styles["Heading 1"].style_id = "2"            # 模拟真实模板数字自编号
    import tempfile

    dest.save(p := tempfile.mktemp(suffix=".docx"))
    dest = Document(p)

    src = Document()
    h = src.add_heading("注入标题", level=1)            # pStyle val=Heading1
    el = _copy.deepcopy(h._p)
    retarget_style_ids([el], src, dest)
    assert el.find(qn("w:pPr")).find(qn("w:pStyle")).get(qn("w:val")) == "2"


def test_retarget_style_ids_skips_resolvable_and_unmatched():
    """宿主已认识该 id → 不动(保护模板自带/fill 产物);名字对不上且无标题级
    对位 → 保持原值(outlineLvl 直写已兜底级别)。"""
    import copy as _copy

    from biaoshu_gen.docx_io import retarget_style_ids

    dest = Document()
    dest.add_heading("宿主", level=1)
    src = Document()
    h1 = src.add_heading("同id可解析", level=1)         # Heading1 在 dest 可解析
    el1 = _copy.deepcopy(h1._p)
    retarget_style_ids([el1], src, dest)
    assert el1.find(qn("w:pPr")).find(qn("w:pStyle")).get(qn("w:val")) == "Heading1"

    h2 = src.add_paragraph("x", style="Quote")          # Quote 在 dest 无同名/无级对位
    el2 = _copy.deepcopy(h2._p)
    retarget_style_ids([el2], src, dest)
    assert el2.find(qn("w:pPr")).find(qn("w:pStyle")).get(qn("w:val")) == "Quote"


def test_retarget_style_ids_falls_back_to_outline_level():
    """宿主标题样式名不同(如自定义名)但定义了 outlineLvl → Heading N 按级别
    对位(动态阅读宿主样式体系的兜底路径)。"""
    import copy as _copy

    from docx.enum.style import WD_STYLE_TYPE

    from biaoshu_gen.docx_io import retarget_style_ids

    dest = Document()
    el = dest.styles["Heading 1"].element            # 移除同名样式,隔离级别对位路径
    el.getparent().remove(el)
    st = dest.styles.add_style("方案章节标题", WD_STYLE_TYPE.PARAGRAPH)
    pPr = st.element.get_or_add_pPr()
    ol = OxmlElement("w:outlineLvl")
    ol.set(qn("w:val"), "0")
    pPr.append(ol)                                      # 一级标题(outlineLvl 0)
    src = Document()
    h = src.add_heading("注入标题", level=1)            # Heading1 → 级别对位
    el = _copy.deepcopy(h._p)
    retarget_style_ids([el], src, dest)
    assert el.find(qn("w:pPr")).find(qn("w:pStyle")).get(qn("w:val")) == \
        dest.styles["方案章节标题"].style_id


def _make_png(width_px: int, height_px: int) -> bytes:
    """程序化生成合法 PNG(IHDR+zlib 扫描线),用于构造已知宽高比的竖版长图。"""
    import struct
    import zlib

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\xff" * (width_px * 3) for _ in range(height_px))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width_px, height_px, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def test_mermaid_tall_picture_scaled_by_height(monkeypatch):
    """竖版长图按宽度缩放会超页高,Word 只显示上半——按高度封顶等比缩小显示全图。"""
    from docx.shared import Inches

    import biaoshu_gen.mermaid_render as mr

    monkeypatch.setattr(mr, "render_mermaid_png", lambda code: _make_png(400, 3000))
    doc = Document()
    markdown_to_docx(doc, "```mermaid\nflowchart TD\n  A-->B\n```\n")
    shape = doc.inline_shapes[0]
    assert shape.height <= Inches(8.0)                 # 不超出可排版页高
    assert abs(shape.width / shape.height - 400 / 3000) < 0.01   # 等比,不变形


def test_ensure_style_fallbacks_synthesizes_missing_heading_style():
    """retarget 映射不到的悬空标题引用:在宿主 styles.xml 合成最小标题样式
    (加粗+级别字号+outlineLvl),标题不再以正文外观显示。"""
    import copy as _copy

    from biaoshu_gen.docx_io import (
        _find_style_by_id, ensure_style_fallbacks, retarget_style_ids,
    )

    src = Document()
    markdown_to_docx(src, "# 注入\n")                  # 走真实渲染链路(带段落 outlineLvl)
    dest = Document()
    el = dest.styles["Heading 1"].element
    el.getparent().remove(el)                          # 宿主无 Heading 1:retarget 失败
    els = [_copy.deepcopy(c) for c in src.element.body.iterchildren()
           if not c.tag.endswith("}sectPr")]
    retarget_style_ids(els, src, dest)
    ensure_style_fallbacks(els, src, dest)

    style = _find_style_by_id(dest, "Heading1")
    assert style is not None                           # 悬空 id 已在宿主包合成
    assert style.name == "Heading 1"
    rPr = style.element.find(qn("w:rPr"))
    assert rPr is not None and rPr.find(qn("w:b")) is not None
    assert rPr.find(qn("w:sz")).get(qn("w:val")) == "32"   # 16pt(半磅单位)
    lvl = style.element.find(qn("w:pPr")).find(qn("w:outlineLvl"))
    assert lvl.get(qn("w:val")) == "0"


_CAPTION_MD = ("| a | b |\n|---|---|\n| 1 | 2 |\n\n表：功能清单\n\n正文。\n\n"
               "```mermaid\nflowchart TD\n  A-->B\n```\n\n图：总体流程\n")


def test_media_captions_numbered_and_centered(monkeypatch):
    """#82:紧随表格/mermaid 的题注自动编号「表N./图N.」并水平置中,表/图独立计数。"""
    import biaoshu_gen.mermaid_render as mr

    monkeypatch.setattr(mr, "render_mermaid_png", lambda code: _MIN_PNG)
    doc = Document()
    markdown_to_docx(doc, _CAPTION_MD)
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    by_text = {p.text.strip(): p for p in doc.paragraphs}
    cap_t, cap_f = by_text["表1. 功能清单"], by_text["图1. 总体流程"]
    assert cap_t.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert cap_f.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert "正文。" in by_text                          # 非题注段不受影响
    assert by_text["正文。"].alignment != WD_ALIGN_PARAGRAPH.CENTER


def test_media_captions_increment_per_media():
    """第二张表编 表2.,不与图计数混淆;已有编号的题注不重复编号。"""
    md = ("| a |\n|---|\n| 1 |\n\n表：清单一\n\n"
          "| b |\n|---|\n| 2 |\n\n表1. 清单二\n\n正文。\n")
    doc = Document()
    markdown_to_docx(doc, md)
    texts = [p.text.strip() for p in doc.paragraphs]
    assert "表1. 清单一" in texts and "表2. 清单二" in texts   # 已有编号被规整


def test_plain_text_after_table_not_caption():
    """表后普通段落(不以 图/表+分隔符 开头)不误判为题注、不居中不编号。"""
    doc = Document()
    markdown_to_docx(doc, "| a |\n|---|\n| 1 |\n\n表中数据说明如下。\n")
    texts = [p.text.strip() for p in doc.paragraphs]
    assert "表中数据说明如下。" in texts
    assert not any(t.startswith("表1.") for t in texts)


def test_bare_short_caption_after_media_numbered(monkeypatch):
    """真实 body.md 的题注是裸名词短语(如「五层纵向贯通架构」)——紧随媒体块、
    短、无句末标点的行也按题注编号居中;句末带。的正文不受影响。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    import biaoshu_gen.mermaid_render as mr

    monkeypatch.setattr(mr, "render_mermaid_png", lambda code: _MIN_PNG)
    doc = Document()
    markdown_to_docx(doc, "| a |\n|---|\n| 1 |\n\n五层纵向贯通架构\n\n正文说明。\n\n"
                     "```mermaid\nflowchart TD\n  A-->B\n```\n\n三集群交付架构\n")
    by = {p.text.strip(): p for p in doc.paragraphs}
    assert "表1. 五层纵向贯通架构" in by
    assert by["表1. 五层纵向贯通架构"].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert "图1. 三集群交付架构" in by
    assert by["图1. 三集群交付架构"].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert by["正文说明。"].alignment != WD_ALIGN_PARAGRAPH.CENTER   # 句末有。:正文不误判


def test_synthesized_fallback_style_has_spacing():
    """合成兜底标题样式须带段前/段后距与行距,否则深层标题与正文挤在一起
    (对齐模板标题样式惯例:260 缇=13 磅,line 360=1.5 倍)。"""
    import copy as _copy

    from biaoshu_gen.docx_io import (
        _find_style_by_id, ensure_style_fallbacks, retarget_style_ids,
    )

    src = Document()
    markdown_to_docx(src, "# 注入\n")
    dest = Document()
    el = dest.styles["Heading 1"].element
    el.getparent().remove(el)
    els = [_copy.deepcopy(c) for c in src.element.body.iterchildren()
           if not c.tag.endswith("}sectPr")]
    retarget_style_ids(els, src, dest)
    ensure_style_fallbacks(els, src, dest)

    sp = _find_style_by_id(dest, "Heading1").element.find(qn("w:pPr")).find(qn("w:spacing"))
    assert sp is not None
    assert sp.get(qn("w:before")) == "260" and sp.get(qn("w:after")) == "260"
    assert sp.get(qn("w:line")) == "360" and sp.get(qn("w:lineRule")) == "auto"


def test_heading_without_style_gets_paragraph_spacing():
    """模板缺 Heading 样式回退的普通段落标题也要有段前/段后距;正文段落不动。"""
    doc = Document()
    el = doc.styles["Heading 3"].element
    el.getparent().remove(el)
    markdown_to_docx(doc, "### 深层标题\n\n正文。\n")
    head = next(p for p in doc.paragraphs if p.text.strip() == "深层标题")
    sp = head._p.pPr.find(qn("w:spacing"))
    assert sp is not None
    assert sp.get(qn("w:before")) == "260" and sp.get(qn("w:after")) == "260"
    body = next(p for p in doc.paragraphs if p.text.strip() == "正文。")
    assert body._p.pPr is None or \
        body._p.pPr.find(qn("w:spacing")) is None         # 正文段不加直接段距


def test_mermaid_picture_horizontally_centered(monkeypatch):
    """#84:插图所在段落水平居中。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    import biaoshu_gen.mermaid_render as mr

    monkeypatch.setattr(mr, "render_mermaid_png", lambda code: _MIN_PNG)
    doc = Document()
    markdown_to_docx(doc, "```mermaid\nflowchart LR\n  A-->B\n```\n\n图：流程\n")
    pic_para = doc.paragraphs[-2]                       # 图段(后一行为题注)
    assert pic_para.runs and pic_para.runs[0].element.findall(
        ".//" + qn("a:blip")), "定位的不是图段"
    assert pic_para.alignment == WD_ALIGN_PARAGRAPH.CENTER
