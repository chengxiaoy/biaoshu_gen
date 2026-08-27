"""fill_skill 单测：以带下划线填空/下划线字符/无空白的合成模板验证填写语义。"""
from pathlib import Path

from docx import Document

from biaoshu_gen.fill_skill import (
    dump_fill_points, fill_all_blanks, fill_blank, fill_cell, find_para,
    find_table, insert_picture_after, replace_in_para, run_fill_plan,
)

# 1x1 透明 PNG（构造插图用，无需 PIL）
_PNG1 = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
         b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
         b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _make_template(path: Path) -> Path:
    d = Document()
    p = d.add_paragraph()
    p.add_run("项目名称：")
    blank = p.add_run("        ")
    blank.underline = True                       # (a) 带下划线的空白 run
    p2 = d.add_paragraph()
    p2.add_run("投标人（签章）：")
    p2.add_run("＿＿＿＿＿＿")                   # (b) 下划线字符 run
    p3 = d.add_paragraph()
    p3.add_run("日期：")                         # (c) 无空白无下划线
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "名称"
    d.save(path)
    return path


def _make_boundary_template(path: Path) -> Path:
    """含 投标人：/投标人（签章）：/投标人地址：/日期：无 四段，覆盖标签边界与空位两种误填。"""
    d = Document()
    p = d.add_paragraph()
    p.add_run("投标人：")
    b = p.add_run("        ")
    b.underline = True                       # 空白 run
    p2 = d.add_paragraph()
    p2.add_run("投标人（签章）：")
    p2.add_run("＿＿＿＿＿＿")                # 下划线字符 run
    p3 = d.add_paragraph()
    p3.add_run("投标人地址：")
    b3 = p3.add_run("        ")
    b3.underline = True
    p4 = d.add_paragraph()
    p4.add_run("日期：无")                    # 无空位
    d.save(path)
    return path


def test_fill_all_blanks_stops_at_label_boundary(tmp_path: Path):
    """前缀匹配须停在标签边界：投标人 命中 投标人：/投标人（签章）：，不得误中 投标人地址。"""
    d = Document(str(_make_boundary_template(tmp_path / "t.docx")))
    n = fill_all_blanks(d, "投标人", "测试公司")
    assert n == 2
    ps = [p.text for p in d.paragraphs]
    assert any(p == "投标人：测试公司" for p in ps)
    assert any(p.startswith("投标人（签章）：测试公司") for p in ps)
    addr = next(p for p in ps if p.startswith("投标人地址"))
    assert "测试公司" not in addr            # 地址段未被触碰


def test_fill_all_blanks_does_not_inject_into_slotless_para(tmp_path: Path):
    """无填空位的段落不硬插值（防 '投标人地址：无' 被塞入公司名）。"""
    d = Document(str(_make_boundary_template(tmp_path / "t.docx")))
    n = fill_all_blanks(d, "日期", "2026-08-20")
    assert n == 0
    p = next(p for p in d.paragraphs if p.text.startswith("日期"))
    assert p.text == "日期：无"              # 原文未变，未插入 run


def test_fill_blank_on_underlined_blank_run(tmp_path: Path):
    d = Document(str(_make_template(tmp_path / "t.docx")))
    fill_blank(d, "项目名称：", "演示项目")
    p = find_para(d, "项目名称：")
    assert p.text == "项目名称：演示项目"
    assert any(r.text == "演示项目" and r.underline for r in p.runs)   # 值落在线上且保留下划线


def test_fill_blank_on_underscore_run(tmp_path: Path):
    d = Document(str(_make_template(tmp_path / "t.docx")))
    fill_blank(d, "投标人（签章）：", "测试公司")
    p = find_para(d, "投标人（签章）：")
    assert p.text == "投标人（签章）：测试公司＿＿"                     # 替换线内并留余线，不附加线后


def test_fill_blank_inserts_underlined_run_when_no_blank(tmp_path: Path):
    d = Document(str(_make_template(tmp_path / "t.docx")))
    fill_blank(d, "日期：", "2026-08-20")
    p = find_para(d, "日期：")
    assert "2026-08-20" in p.text
    assert any("2026-08-20" in r.text and r.underline for r in p.runs)  # 插入的 run 自带下划线


def test_replace_and_cell_and_picture(tmp_path: Path):
    path = _make_template(tmp_path / "t.docx")
    img = tmp_path / "lic.png"
    img.write_bytes(_PNG1)
    d = Document(str(path))
    replace_in_para(d, "日期：", "日期", "签署日期")
    assert find_para(d, "签署日期：").text.startswith("签署日期")
    fill_cell(d, 0, 1, 1, "1 套")
    assert d.tables[0].rows[1].cells[1].paragraphs[0].text == "1 套"
    insert_picture_after(d, "项目名称：", str(img), caption="附：证照")
    assert len(d.inline_shapes) == 1
    assert any("附：证照" in p.text for p in d.paragraphs)


def test_run_fill_plan_batch_and_errors(tmp_path: Path):
    """声明式清单：一次执行多种 op；单条失败收集错误不中断。"""
    path = _make_template(tmp_path / "t.docx")
    img = tmp_path / "lic.png"
    img.write_bytes(_PNG1)
    plan = [
        {"op": "blank", "prefix": "项目名称：", "value": "演示项目"},
        {"op": "cell", "table_header": ["名称"], "row": 1, "col": 1, "value": "1 套"},
        {"op": "picture", "prefix": "项目名称：", "img": str(img)},
        {"op": "blank", "prefix": "不存在的段落：", "value": "X"},      # 应报错不中断
    ]
    out = tmp_path / "out.docx"
    errors = run_fill_plan(str(path), str(out), plan)
    d = Document(str(out))
    assert find_para(d, "项目名称：").text == "项目名称：演示项目"      # 前三条已生效
    assert len(d.inline_shapes) == 1
    assert len(errors) == 1 and "不存在的段落" in errors[0]


def test_fill_blank_before_label_paren_annotation(tmp_path: Path):
    """「空位在标签前」形态:__(标签)——下划线空位 run 后紧跟括号注记(commercial 部分
    的主要文体)。仅括号内是单一标签时才填,多标签并列(如 项目名称、政府采购编号)
    归属不明,不填留给 LLM。"""
    d = Document()
    p = d.add_paragraph()
    p.add_run("我系参加")
    p.add_run("                      ").underline = True
    p.add_run("（项目名称），委托代理编号：")
    p.add_run("               ").underline = True
    p2 = d.add_paragraph()
    p2.add_run("本公司参加")
    p2.add_run("        ").underline = True
    p2.add_run("（单位名称）的")
    p3 = d.add_paragraph()                                 # 多标签括号:不填
    p3.add_run("响应")
    p3.add_run("                     ").underline = True
    p3.add_run("（项目名称、政府采购编号、采购代理编号）响应文件")
    src = tmp_path / "t.docx"
    d.save(src)

    from biaoshu_gen.fill_skill import fill_blank_before_label
    d2 = Document(str(src))
    assert fill_blank_before_label(d2, "项目名称", "实训室项目") == 1
    texts = [x.text for x in d2.paragraphs]
    assert texts[0].startswith("我系参加实训室项目（项目名称）")
    assert "本公司参加        （单位名称）的" == texts[1]      # 单位名称未给值不动
    assert "（项目名称、政府采购编号" in texts[2] and "实训室项目" not in texts[2]


def test_fill_blank_before_label_in_prefill_known(tmp_path: Path, monkeypatch):
    """预填第三模式:commercial 文体的 __(标签) 也由代码预填,prompt 标注勿重复。"""
    monkeypatch.chdir(tmp_path)
    from docx import Document

    from biaoshu_gen.business import ensure_business_fields
    from biaoshu_gen.fill_context import prefill_known
    from biaoshu_gen.state import BidState, run_dir

    tpl = tmp_path / "标书模板.docx"
    d = Document()
    p = d.add_paragraph()
    p.add_run("本公司参加")
    p.add_run("        ").underline = True
    p.add_run("（单位名称）承建")
    p2 = d.add_paragraph()
    p2.add_run("我系参加")
    p2.add_run("        ").underline = True
    p2.add_run("（项目名称）磋商")
    d.save(tpl)
    state = BidState(run_id="run-1", template_docx_path=str(tpl))
    ensure_business_fields(state)
    fp = run_dir(state) / "03_facts.yaml"
    fp.write_text(fp.read_text(encoding="utf-8")
                  + 'template_fields:\n  项目名称: 演示项目\n', encoding="utf-8")

    doc = Document(str(tpl))
    summary = prefill_known(doc, state)
    texts = [x.text for x in doc.paragraphs]
    assert "本公司参加某某科技有限公司（待替换）（单位名称）承建" == texts[0]
    assert "我系参加演示项目（项目名称）磋商" == texts[1]
    assert "投标人×1" in summary and "项目名称×1" in summary


def test_dump_fill_points_shows_full_header_text(tmp_path: Path):
    """表头地图不得截断:模型须能逐字回显完整表头作为 table_header 关键词。

    真实事故:地图把'参数（型号、规格及参数说明）'截成 8 字,模型回显截断串
    (甚至自行补字'等'),find_table 必然失配。
    """
    d = Document()
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "参数（型号、规格及参数说明）"
    t.cell(0, 1).text = "备注"
    src = tmp_path / "t.docx"
    d.save(src)

    doc = Document(str(src))
    assert "参数（型号、规格及参数说明）" in dump_fill_points(doc)
    assert find_table(doc, "参数（型号、规格及参数说明）", "备注") == 0   # 回环:地图所示即可用


def test_dump_fill_points(tmp_path: Path):
    path = _make_template(tmp_path / "t.docx")
    d = Document(str(path))
    text = dump_fill_points(d)
    assert "项目名称" in text and "[T0]" in text and "名称" in text


def test_run_fill_plan_label_op_fills_mid_paragraph_blanks(tmp_path: Path):
    """label op:按标签填段中部填空(采购代理编号:__ 项目名称:__ 同段),填全部命中;
    未命中报错收集。"""
    from docx import Document

    d = Document()
    p = d.add_paragraph()
    p.add_run("采购代理编号：")
    p.add_run("＿＿＿")
    p.add_run("  项目名称：")
    p.add_run("＿＿＿")
    src = tmp_path / "t.docx"
    d.save(src)

    plan = [{"op": "label", "label": "项目名称：", "value": "演示项目"}]
    out = tmp_path / "out.docx"
    errors = run_fill_plan(str(src), str(out), plan)
    assert errors == []
    texts = [x.text for x in Document(str(out)).paragraphs]
    assert texts[0] == "采购代理编号：＿＿＿  项目名称：演示项目＿＿"  # 只填标签命中的空,留余线

    errors2 = run_fill_plan(str(src), str(tmp_path / "o2.docx"),
                            [{"op": "label", "label": "不存在的标签：", "value": "X"}])
    assert len(errors2) == 1 and "不存在的标签" in errors2[0]


def test_label_op_fills_underlined_space_runs_mid_paragraph(tmp_path: Path):
    """真实模板形态:填空位是带下划线格式的纯空格 run,段中多处;不得被边界跳过循环吃掉。"""
    d = Document()
    p = d.add_paragraph()
    p.add_run("采购代理编号：")
    p.add_run("                 ").underline = True
    p.add_run(" 项目名称：")
    p.add_run("           ").underline = True
    src = tmp_path / "t.docx"
    d.save(src)

    errors = run_fill_plan(str(src), str(tmp_path / "out.docx"), [
        {"op": "label", "label": "采购代理编号", "value": "HN-001"},
        {"op": "label", "label": "项目名称", "value": "演示项目"},
    ])
    assert errors == []
    text = Document(str(tmp_path / "out.docx")).paragraphs[0].text
    assert text.startswith("采购代理编号：HN-001")
    assert "项目名称：演示项目" in text


def test_label_op_fills_mid_run_underscore_segment(tmp_path: Path):
    """真实模板形态:整行一个 run,'小写：____ 大写：____'下划线段后同 run 还有文字。"""
    d = Document()
    d.add_paragraph("报价金额合计：小写：_______________ 大写：_______________")
    src = tmp_path / "t.docx"
    d.save(src)

    errors = run_fill_plan(str(src), str(tmp_path / "out.docx"), [
        {"op": "label", "label": "小写", "value": "100000"},
        {"op": "label", "label": "大写", "value": "拾万元整"},
    ])
    assert errors == []
    text = Document(str(tmp_path / "out.docx")).paragraphs[0].text
    assert text == "报价金额合计：小写：100000＿＿ 大写：拾万元整＿＿"


def test_label_op_rejects_longer_label_at_para_start(tmp_path: Path):
    """段首匹配须验证标签后边界:'投标人' 不得误填 '投标人地址：__' 的空位。"""
    d = Document()
    p = d.add_paragraph()
    p.add_run("投标人地址：")
    b = p.add_run("        ")
    b.underline = True
    src = tmp_path / "t.docx"
    d.save(src)

    errors = run_fill_plan(str(src), str(tmp_path / "out.docx"),
                           [{"op": "label", "label": "投标人", "value": "某公司"}])
    assert len(errors) == 1
    text = Document(str(tmp_path / "out.docx")).paragraphs[0].text
    assert "某公司" not in text


def test_replace_in_para_normalizes_paren_width(tmp_path: Path):
    """模板半角括号(夹空格) vs 模型全角输出:宽度归一化后仍能定位替换,原文其余部分不动。"""
    d = Document()
    d.add_paragraph("致             (采购人、采购代理机构)：")
    src = tmp_path / "t.docx"
    d.save(src)

    errors = run_fill_plan(str(src), str(tmp_path / "out.docx"), [
        {"op": "replace", "prefix": "致",
         "old": "（采购人、采购代理机构）", "new": "某某科技有限公司"},
    ])
    assert errors == []
    text = Document(str(tmp_path / "out.docx")).paragraphs[0].text
    assert text == "致             某某科技有限公司："


def test_cell_op_matches_table_despite_nbsp_and_caption_prefix(tmp_path: Path):
    """真实模板形态:表头单元格含不间断空格(备\\xa0\\xa0注),且模型会把表标题拼进
    表头关键词(货物说明一览表：序号)——find_table 须归一化匹配并容忍冒号前缀。"""
    d = Document()
    d.add_paragraph("货物说明一览表：")
    t = d.add_table(rows=2, cols=3)
    t.cell(0, 0).text = "序号"
    t.cell(0, 1).text = "货物名称"
    t.cell(0, 2).text = "备  注"
    src = tmp_path / "t.docx"
    d.save(src)

    errors = run_fill_plan(str(src), str(tmp_path / "out.docx"), [
        {"op": "cell", "table_header": ["货物说明一览表：序号", "货物名称", "备  注"],
         "row": 1, "col": 1, "value": "工业机器人"},
    ])
    assert errors == []
    d2 = Document(str(tmp_path / "out.docx"))
    assert d2.tables[0].cell(1, 1).text == "工业机器人"


def test_replace_keeps_unrelated_blank_runs_in_same_para(tmp_path: Path):
    """replace 只重写命中 run,不整段合并——同段下划线填空位须保留给后续 label op。

    真实事故:op[1] replace「（项目名称）」整段拍平后,op[2] label「政府采购编号」
    的空位 run 已被清空,永远 miss。
    """
    d = Document()
    p = d.add_paragraph()
    p.add_run("根据贵方为           ")
    p.add_run("（项目名称）的磋商邀请（政府采购编号：")
    b = p.add_run("      ")
    b.underline = True
    p.add_run(" ），")
    src = tmp_path / "t.docx"
    d.save(src)

    errors = run_fill_plan(str(src), str(tmp_path / "out.docx"), [
        {"op": "replace", "prefix": "根据贵方为", "old": "（项目名称）", "new": "演示项目"},
        {"op": "label", "label": "政府采购编号", "value": "HN-001"},
    ])
    assert errors == []
    d2 = Document(str(tmp_path / "out.docx"))
    p2 = d2.paragraphs[0]
    assert p2.text == "根据贵方为           演示项目的磋商邀请（政府采购编号：HN-001 ），"
    assert any(r.underline for r in p2.runs)            # 下划线空位 run 未被合并清除


def test_label_op_tolerates_missing_colon_and_cell_grows_rows(tmp_path: Path):
    """label 无冒号也能命中(跳边界符);cell 行不够自动加行。"""
    from docx import Document

    from biaoshu_gen.fill_skill import run_fill_plan

    d = Document()
    p = d.add_paragraph()
    p.add_run("采购代理编号：")
    p.add_run("＿＿＿")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "名称"
    src = tmp_path / "t.docx"
    d.save(src)

    out = tmp_path / "out.docx"
    errors = run_fill_plan(str(src), str(out), [
        {"op": "label", "label": "采购代理编号", "value": "HN-2026-001"},   # 无冒号
        {"op": "cell", "table_header": ["名称"], "row": 2, "col": 1, "value": "新增行值"},  # 超行
    ])
    assert errors == []
    d2 = Document(str(out))
    assert "HN-2026-001" in d2.paragraphs[0].text
    assert len(d2.tables[0].rows) == 3 and d2.tables[0].cell(2, 1).text == "新增行值"
