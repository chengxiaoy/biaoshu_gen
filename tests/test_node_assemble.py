from pathlib import Path

from docx import Document

from biaoshu_gen.nodes import assemble as asm
from biaoshu_gen.schemas import TenderMetadata
from biaoshu_gen.state import BidState, run_dir


def _forms_docx(path: Path) -> None:
    """底稿候选：模板壳 + 已填的投标函与商务内容（技术仍是空壳）。"""
    d = Document()
    d.add_heading("投标函", level=1)
    d.add_paragraph("公司：测试投标人公司")
    d.add_heading("资格证明文件", level=1)
    d.add_paragraph("营业执照复印件")
    d.add_heading("商务部分", level=1)
    d.add_paragraph("业绩：智慧城市监测平台合同")
    d.add_heading("技术部分", level=1)
    d.add_paragraph("（技术方案格式自定）")
    d.save(path)


def _deviation_docx(path: Path) -> None:
    """整本模板副本 + 偏离表（底稿没有的区间）。"""
    d = Document()
    d.add_heading("投标函", level=1)
    d.add_paragraph("公司：测试投标人公司")
    d.add_heading("偏离表", level=1)
    d.add_paragraph("偏离说明：全部无偏离")
    d.save(path)


def _state(tmp_path: Path, monkeypatch, version: int = 0, **paths) -> BidState:
    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    body = d / "05_body"
    body.mkdir(parents=True, exist_ok=True)
    (body / "body.md").write_text("# 总体思路\n\n总体思路内容。", encoding="utf-8")
    for name in ("forms", "deviation"):
        p = d / "06_fill" / name / f"{name}.docx"
        p.parent.mkdir(parents=True, exist_ok=True)
        maker = {"forms": _forms_docx, "deviation": _deviation_docx}[name]
        if paths.get(name, True):
            maker(p)
    return BidState(
        run_id="run-1",
        metadata=TenderMetadata(project_name="演示项目"),
        body_md_path=str(body / "body.md"),
        forms_docx_path=str(d / "06_fill/forms/forms.docx") if paths.get("forms", True) else "",
        deviation_docx_path=str(d / "06_fill/deviation/deviation.docx") if paths.get("deviation") else "",
        draft_version=version,
    )


def test_assemble_replaces_anchored_sections_in_template_order(tmp_path: Path, monkeypatch):
    """技术按锚标题区间替换（非追加）：壳不重复、顺序跟模板、正文进锚点；
    商务内容随合并后的 forms 底稿直接就位。"""
    state = _state(tmp_path, monkeypatch, forms=True, deviation=False)
    updates = asm.assemble_node(state)
    doc = Document(updates["draft_docx_path"])
    texts = [p.text for p in doc.paragraphs]

    # 各锚标题只出现一次（无重复壳）
    for h in ("投标函", "商务部分", "技术部分"):
        assert texts.count(h) == 1, (h, texts)
    # 填充内容在位
    assert "公司：测试投标人公司" in texts            # forms 底稿
    assert "业绩：智慧城市监测平台合同" in texts        # 商务内容随 forms 底稿就位
    # 技术部分空壳被正文替换
    assert "（技术方案格式自定）" not in texts
    assert "总体思路内容。" in texts
    # 顺序跟模板：商务内容 < 技术部分标题 < 正文内容
    assert texts.index("业绩：智慧城市监测平台合同") < texts.index("技术部分")
    assert texts.index("技术部分") < texts.index("总体思路内容。")


def test_assemble_appends_only_missing_deviation_range(tmp_path: Path, monkeypatch):
    """底稿无偏离表区间 -> 仅追加填充文档中的偏离表区间，不整本拼接。"""
    state = _state(tmp_path, monkeypatch, forms=True, deviation=True)
    updates = asm.assemble_node(state)
    doc = Document(updates["draft_docx_path"])
    texts = [p.text for p in doc.paragraphs]

    assert texts.count("偏离表") == 1
    assert "偏离说明：全部无偏离" in texts
    assert texts.count("投标函") == 1               # deviation 整本未拼接进来


def test_assemble_fallback_without_heading_styles(tmp_path: Path, monkeypatch):
    """无标题样式的底稿：正文尾部追加 + deviation 兜底去重追加，不崩溃。"""
    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    body = d / "05_body"
    body.mkdir(parents=True, exist_ok=True)
    (body / "body.md").write_text("# 总体思路\n\n总体思路内容。", encoding="utf-8")

    plain = Document()                                # 无 Heading 样式
    plain.add_paragraph("封面页")
    plain.add_paragraph("商务部分")
    plain.add_paragraph("（此处填写）")
    forms_p = d / "06_fill" / "forms" / "forms.docx"
    forms_p.parent.mkdir(parents=True, exist_ok=True)
    plain.save(forms_p)

    dev = Document()                                  # 整本无标题 + 偏离已填
    dev.add_paragraph("封面页")
    dev.add_paragraph("偏离说明：全部无偏离")
    dev_p = d / "06_fill" / "deviation" / "deviation.docx"
    dev_p.parent.mkdir(parents=True, exist_ok=True)
    dev.save(dev_p)

    state = BidState(
        run_id="run-1", body_md_path=str(body / "body.md"),
        forms_docx_path=str(forms_p), deviation_docx_path=str(dev_p),
    )
    updates = asm.assemble_node(state)
    doc = Document(updates["draft_docx_path"])
    texts = [p.text for p in doc.paragraphs]
    assert "总体思路内容。" in texts                   # 正文尾部追加
    assert "偏离说明：全部无偏离" in texts             # deviation 兜底追加
    assert texts.count("封面页") == 1                  # 壳文本去重


def test_assemble_version_increments(tmp_path: Path, monkeypatch):
    state = _state(tmp_path, monkeypatch, version=1, forms=True, deviation=False)
    updates = asm.assemble_node(state)
    assert Path(updates["draft_docx_path"]).name == "标书草稿_v2.docx"
    assert (run_dir(state) / "07_draft" / "latest.txt").read_text(encoding="utf-8") == "2"


def test_assemble_concatenates_parts_in_template_order(tmp_path: Path, monkeypatch):
    """parts.yaml 存在时:各 part 按文档原序拼接,technical 注入 body,
    有填充产物用产物、跳过的桶用原始 part。"""
    from biaoshu_gen.nodes import split_template as st

    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    ws = d / "02_template"
    ws.mkdir(parents=True)
    tpl = ws / "标书模板.docx"
    doc = Document()
    doc.add_paragraph("第五章 响应文件组成")
    for title in ("一、磋商响应声明", "三、保证金", "六、项目实施方案", "七、合同条款偏离表"):
        doc.add_heading(title, level=2)
        doc.add_paragraph(f"{title} 模板正文。")
    doc.save(tpl)
    state0 = BidState(run_id="run-1", tender_path=str(tpl), template_docx_path=str(tpl))
    parts = st.split_template_node(state0)["template_parts"]

    body = d / "05_body"
    body.mkdir(parents=True)
    (body / "body.md").write_text("# 总体思路\n\n总体思路内容。", encoding="utf-8")

    def _filled(bucket: str, marker: str) -> str:
        src = Document(parts[bucket])
        src.add_paragraph(marker)
        out = d / "06_fill" / bucket / f"{bucket}.docx"
        out.parent.mkdir(parents=True, exist_ok=True)
        src.save(out)
        return str(out)

    state = BidState(
        run_id="run-1", body_md_path=str(body / "body.md"),
        template_docx_path=str(tpl), template_parts=parts,
        forms_docx_path=_filled("forms", "表单已填标记"),
        deviation_docx_path="",                        # deviation 跳过 -> 用原始 part
    )
    updates = asm.assemble_node(state)
    texts = [p.text for p in Document(updates["draft_docx_path"]).paragraphs if p.text.strip()]
    joined = "\n".join(texts)
    # 顺序:前言+保证金(forms part 内) < forms 已填 < technical body < deviation 原始 part
    assert joined.index("第五章 响应文件组成") < joined.index("一、磋商响应声明")
    assert joined.index("表单已填标记") < joined.index("总体思路内容")
    assert joined.index("总体思路内容") < joined.index("七、合同条款偏离表 模板正文。")
    assert "三、保证金 模板正文。" in joined                        # forms part 保留模板原文
    assert "六、项目实施方案 模板正文。" not in joined               # 技术区间被 body 替换
    assert "总体思路内容" in joined                                  # body 已注入


def test_assemble_migrates_images_from_parts(tmp_path: Path, monkeypatch):
    """跨文档搬运须迁移图片关系:forms 产物里的插图装配后 rId 须在壳包可解析。

    真实事故:装配只搬 body 元素,a:blip@r:embed 仍指源文档关系表——Word 打开
    显示空白,而 inline_shapes 计数照常(只数 XML 不解析关系),具有欺骗性。
    """
    from io import BytesIO

    from docx.oxml.ns import qn

    from biaoshu_gen.nodes import split_template as st

    _PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    ws = d / "02_template"
    ws.mkdir(parents=True)
    tpl = ws / "标书模板.docx"
    doc = Document()
    doc.add_paragraph("第五章 响应文件组成")               # 无标题前导段 -> forms 桶
    for title in ("一、磋商响应声明", "六、项目实施方案", "七、合同条款偏离表"):
        doc.add_heading(title, level=2)
        doc.add_paragraph(f"{title} 模板正文。")
    doc.save(tpl)
    parts = st.split_template_node(
        BidState(run_id="run-1", tender_path=str(tpl), template_docx_path=str(tpl))
    )["template_parts"]

    frm = Document(parts["forms"])
    frm.add_paragraph("资质证明：")
    frm.add_paragraph().add_run().add_picture(BytesIO(_PNG))
    frm_out = d / "06_fill" / "forms" / "forms.docx"
    frm_out.parent.mkdir(parents=True, exist_ok=True)
    frm.save(frm_out)

    body = d / "05_body"
    body.mkdir(parents=True)
    (body / "body.md").write_text("# 总体思路\n\n内容。", encoding="utf-8")
    state = BidState(run_id="run-1", body_md_path=str(body / "body.md"),
                     template_docx_path=str(tpl), template_parts=parts,
                     forms_docx_path=str(frm_out))

    updates = asm.assemble_node(state)

    draft = Document(updates["draft_docx_path"])
    blips = list(draft.element.body.iter(qn("a:blip")))
    assert len(blips) == 1
    rid = blips[0].get(qn("r:embed"))
    assert rid in draft.part.rels                                # rId 在壳包内注册
    assert draft.part.rels[rid].target_part.blob == _PNG         # 指向同一图片字节
    assert len(draft.inline_shapes) == 1


def test_assemble_stitches_interleaved_runs_in_document_order(tmp_path: Path, monkeypatch):
    """同桶多区间:附加段的独立填充产物按其 first_element_index 插回原位,
    不再整桶前置——software 大纲乱序(身份证明/授权书跑到投标函前)的回归锁。"""
    from biaoshu_gen.nodes import split_template as st

    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    ws = d / "02_template"
    ws.mkdir(parents=True)
    tpl = ws / "标书模板.docx"
    doc = Document()
    doc.add_paragraph("第七章 投标文件的格式")           # forms run1 头
    for title in ("投标函及报价文件", "采购需求偏离表",
                  "（四）法定代表人身份证明", "资格证明文件", "六、项目实施方案"):
        doc.add_heading(title, level=2)
        doc.add_paragraph(f"{title} 模板正文。")
    doc.save(tpl)
    parts = st.split_template_node(
        BidState(run_id="run-1", tender_path=str(tpl), template_docx_path=str(tpl))
    )["template_parts"]
    man = st.read_parts_yaml(d)
    keys = [e["key"] for e in man["entries"]]
    assert "forms_2" in keys and \
        [e for e in man["entries"] if e["key"] == "forms"][0]["primary"] is True
    # （四）+资格证明 在偏离表之后 -> forms 第二区间

    # 附加段独立填充产物(原始 part + 标记),主 forms 用真实填充
    def _product(src: str, out: Path, marker: str):
        out.parent.mkdir(parents=True, exist_ok=True)
        dd = Document(src); dd.add_paragraph(marker); dd.save(out); return str(out)

    body = d / "05_body"; body.mkdir(parents=True)
    (body / "body.md").write_text("# 总体\n思路内容。", encoding="utf-8")
    forms2_src = next(e["path"] for e in man["entries"] if e["key"] == "forms_2")
    filled_forms = d / "06_fill" / "forms" / "forms.docx"
    filled_forms.parent.mkdir(parents=True, exist_ok=True)
    ff = Document(parts["forms"]); ff.add_paragraph("投标函已填"); ff.save(filled_forms)

    state = BidState(run_id="run-1", body_md_path=str(body / "body.md"),
                     template_docx_path=str(tpl), template_parts=parts,
                     forms_docx_path=str(filled_forms),
                     extra_products={
                         "forms_2": _product(forms2_src, d / "06_fill" / "forms_2" /
                                             "forms.docx", "身份证明已填")})
    updates = asm.assemble_node(state)
    joined = "\n".join(p.text for p in Document(updates["draft_docx_path"]).paragraphs
                       if p.text.strip())
    i_chapter = joined.index("第七章")
    i_letter = joined.index("投标函已填")
    i_dev = joined.index("采购需求偏离表 模板正文。")
    i_qual = joined.index("资格证明文件 模板正文。")
    i_mid = joined.index("身份证明已填")                    # 附加段产物尾部标记
    assert i_chapter < i_letter < i_dev < i_qual < i_mid   # 顺序还原,不再整桶前置


def test_assemble_guards_against_bloated_product(tmp_path: Path, monkeypatch):
    """膨胀守卫:桶级产物元素数远超模板切片(harness 复述扩写)时弃用产物,
    回退原始 part——software 实测 flash 把小切片扩成数百元素整章。"""
    from biaoshu_gen.nodes import split_template as st

    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    ws = d / "02_template"
    ws.mkdir(parents=True)
    tpl = ws / "标书模板.docx"
    doc = Document()
    doc.add_paragraph("第七章 投标文件的格式")           # forms 切片:3 元素(第七章+投标函)
    doc.add_heading("投标函及报价文件", level=2)
    doc.add_paragraph("投标函及报价文件 模板正文。")
    doc.add_heading("六、项目实施方案", level=2)
    doc.add_paragraph("六、项目实施方案 模板正文。")
    doc.save(tpl)
    parts = st.split_template_node(
        BidState(run_id="run-1", tender_path=str(tpl), template_docx_path=str(tpl))
    )["template_parts"]

    bloated = d / "06_fill" / "forms" / "forms.docx"      # 产物:复述扩写
    bloated.parent.mkdir(parents=True, exist_ok=True)
    bd = Document()
    bd.add_paragraph("第七章 投标文件的格式")
    for i in range(60):                                          # 61 元素 >> 3*3+30
        bd.add_paragraph(f"复述内容{i}")
    bd.save(bloated)

    body = d / "05_body"; body.mkdir(parents=True)
    (body / "body.md").write_text("# 总体\n思路内容。", encoding="utf-8")
    state = BidState(run_id="run-1", body_md_path=str(body / "body.md"),
                     template_docx_path=str(tpl), template_parts=parts,
                     forms_docx_path=str(bloated))
    updates = asm.assemble_node(state)
    texts = [p.text for p in Document(updates["draft_docx_path"]).paragraphs]
    assert not any("复述内容" in t for t in texts)               # 产物被守卫拒绝
    assert sum(1 for t in texts if t == "第七章 投标文件的格式") == 1  # 原始切片就位


def _write_technical_parts(d: Path, part_docx: Path) -> None:
    """手工构造单 technical run 的 parts.yaml(assemble 只读清单,不经 split 节点)。"""
    import yaml

    parts_dir = d / "02_template" / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    (parts_dir / "parts.yaml").write_text(yaml.safe_dump({
        "entries": [{"key": "technical", "bucket": "technical", "path": str(part_docx),
                     "primary": True, "first_element_index": 0}],
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_assemble_keeps_body_heading_levels_and_numbers(tmp_path: Path, monkeypatch):
    """#83(2026-09-09):编号与层级解耦——编号恒为 1./1.1/1.1.1(#80),层级按锚点
    挂接(锚 H4 时正文 #→H4/##→H5/###→H6):导航/目录里技术章节嵌在宿主
    「技术部分>技术方案」之下,不再以顶层章节姿态横插在格式章中间。"""
    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    ws = d / "02_template"
    ws.mkdir(parents=True)
    tpl = ws / "标书模板.docx"
    doc = Document()
    doc.add_paragraph("第五章 响应文件组成")
    doc.add_heading("（三）技术部分", level=3)          # 锚在格式章深处 H3
    doc.add_heading("技术方案", level=4)
    doc.add_paragraph("（正文格式说明）")
    doc.save(tpl)
    part = d / "02_template" / "技术方案部分.docx"
    part_doc = Document()
    part_doc.add_heading("技术方案", level=4)           # part 切片:锚 H4 在其中
    part_doc.save(part)
    _write_technical_parts(d, part)

    body = d / "05_body"
    body.mkdir(parents=True)
    (body / "body.md").write_text(
        "# 总体思路\n\n总体内容。\n\n## 实施要点\n\n### 进度安排\n\n要点内容。", encoding="utf-8")
    state = BidState(run_id="run-1", body_md_path=str(body / "body.md"),
                     template_docx_path=str(tpl), forms_docx_path="", deviation_docx_path="")
    updates = asm.assemble_node(state)
    styles = {p.text.strip(): p.style.name
              for p in Document(updates["draft_docx_path"]).paragraphs if p.text.strip()}
    assert styles["1. 总体思路"] == "Heading 4"         # 级别随锚,编号仍 1.
    assert styles["1.1 实施要点"] == "Heading 5"
    assert styles["1.1.1 进度安排"] == "Heading 6"


def test_assemble_outline_level_survives_foreign_style_ids(tmp_path: Path, monkeypatch):
    """真实标书模板的 styleId 是数字自编号,scratch 渲染产物 pStyle=Heading4
    解析不到 -> 标题塌回 Normal(run-20260908-215413 实测)。大纲级别须直接写
    w:outlineLvl 兜底,不依赖 pStyle 能否在宿主包解析(通用解法)。"""
    from docx.oxml.ns import qn

    def _outline(p):
        pPr = p._p.pPr
        el = pPr.find(qn("w:outlineLvl")) if pPr is not None else None
        return el.get(qn("w:val")) if el is not None else None

    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    ws = d / "02_template"
    ws.mkdir(parents=True)
    tpl = ws / "标书模板.docx"
    doc = Document()
    doc.add_paragraph("第五章 响应文件组成")
    doc.add_heading("技术方案", level=4)
    doc.styles["Heading 4"].style_id = "T4"        # 模拟真实模板数字/自编号 styleId
    doc.styles["Heading 5"].style_id = "T5"
    doc.save(tpl)
    part = d / "02_template" / "技术方案部分.docx"
    part_doc = Document()
    part_doc.add_heading("技术方案", level=4)
    part_doc.save(part)
    _write_technical_parts(d, part)

    body = d / "05_body"
    body.mkdir(parents=True)
    (body / "body.md").write_text("# 总体思路\n\n总体内容。\n\n## 实施要点\n\n要点内容。",
                                  encoding="utf-8")
    state = BidState(run_id="run-1", body_md_path=str(body / "body.md"),
                     template_docx_path=str(tpl), forms_docx_path="", deviation_docx_path="")
    updates = asm.assemble_node(state)
    paras = {p.text.strip(): p
             for p in Document(updates["draft_docx_path"]).paragraphs if p.text.strip()}
    assert _outline(paras["1. 总体思路"]) == "3"        # 锚 H4:# → outlineLvl 3(0-based)
    assert _outline(paras["1.1 实施要点"]) == "4"       # ## → outlineLvl 4
    # pStyle 按宿主样式表语义对位后可解析——标题显示样式不再与正文相同
    assert paras["1. 总体思路"].style.name == "Heading 4"
    assert paras["1.1 实施要点"].style.name == "Heading 5"


def test_assemble_numbers_headings_at_anchor_h1(tmp_path: Path, monkeypatch):
    """#80:锚 H1(常见章级)时 #→"1." H1、##→"1.1" H2、###→"1.1.1" H3。"""
    from biaoshu_gen.nodes import split_template as st

    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    ws = d / "02_template"
    ws.mkdir(parents=True)
    tpl = ws / "标书模板.docx"
    doc = Document()
    doc.add_paragraph("第五章 响应文件组成")
    for title, level in (("一、磋商响应声明", 2), ("六、项目实施方案", 1),
                         ("七、合同条款偏离表", 2)):
        doc.add_heading(title, level=level)
        doc.add_paragraph(f"{title} 模板正文。")
    doc.save(tpl)
    parts = st.split_template_node(
        BidState(run_id="run-1", tender_path=str(tpl), template_docx_path=str(tpl))
    )["template_parts"]

    body = d / "05_body"
    body.mkdir(parents=True)
    (body / "body.md").write_text(
        "# 总体思路\n\n总体内容。\n\n## 实施要点\n\n### 进度安排\n\n安排内容。", encoding="utf-8")
    state = BidState(run_id="run-1", body_md_path=str(body / "body.md"),
                     template_docx_path=str(tpl), template_parts=parts,
                     forms_docx_path="", deviation_docx_path="")
    updates = asm.assemble_node(state)
    styles = {p.text.strip(): p.style.name
              for p in Document(updates["draft_docx_path"]).paragraphs if p.text.strip()}
    assert styles["1. 总体思路"] == "Heading 1"
    assert styles["1.1 实施要点"] == "Heading 2"
    assert styles["1.1.1 进度安排"] == "Heading 3"


def test_assemble_renders_table_and_mermaid(tmp_path: Path, monkeypatch):
    """#79:正文表格渲染为真 docx 表格、mermaid 渲染为图片经关系迁移入壳包。"""
    import biaoshu_gen.mermaid_render as mr

    from docx.oxml.ns import qn

    _PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
    monkeypatch.setattr(mr, "render_mermaid_png", lambda code: _PNG)

    state = _state(tmp_path, monkeypatch)
    Path(state.body_md_path).write_text(
        "# 总体思路\n\n| 功能 | 描述 |\n|---|---|\n| 统一认证 | 单点登录 |\n\n"
        "## 实施要点\n\n```mermaid\nflowchart LR\n  A-->B\n```\n\n图：总体流程\n",
        encoding="utf-8")
    updates = asm.assemble_node(state)
    doc = Document(updates["draft_docx_path"])

    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert "统一认证" in cells and "单点登录" in cells            # 真表格在草稿中
    assert not any("|" in p.text for p in doc.paragraphs)         # 管道文本不残留
    assert len(doc.inline_shapes) == 1                            # mermaid 图入稿
    blip = next(doc.element.body.iter(qn("a:blip")))
    rid = blip.get(qn("r:embed"))
    assert rid in doc.part.rels                                   # 关系迁移:壳包可解析
    assert doc.part.rels[rid].target_part.blob == _PNG
    texts = [p.text for p in doc.paragraphs]
    assert "图1. 总体流程" in texts                                # 图题保留并自动编号
