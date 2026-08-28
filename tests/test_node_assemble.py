from pathlib import Path

from docx import Document

from biaoshu_gen.nodes import assemble as asm
from biaoshu_gen.schemas import TenderMetadata
from biaoshu_gen.state import BidState, run_dir


def _forms_docx(path: Path) -> None:
    """底稿候选：模板壳 + 已填的投标函（商务/技术仍是空壳）。"""
    d = Document()
    d.add_heading("投标函", level=1)
    d.add_paragraph("公司：测试投标人公司")
    d.add_heading("资格证明文件", level=1)
    d.add_paragraph("营业执照复印件")
    d.add_heading("商务部分", level=1)
    d.add_paragraph("（此处附业绩与团队）")
    d.add_heading("技术部分", level=1)
    d.add_paragraph("（技术方案格式自定）")
    d.save(path)


def _commercial_docx(path: Path) -> None:
    """整本模板副本，其中商务部分已填。"""
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
    (body / "body.md").write_text("# 1 总体思路\n\n总体思路内容。", encoding="utf-8")
    for name in ("forms", "commercial", "deviation"):
        p = d / "06_fill" / name / f"{name}.docx"
        p.parent.mkdir(parents=True, exist_ok=True)
        maker = {"forms": _forms_docx, "commercial": _commercial_docx,
                 "deviation": _deviation_docx}[name]
        if paths.get(name, True):
            maker(p)
    return BidState(
        run_id="run-1",
        metadata=TenderMetadata(project_name="演示项目"),
        body_md_path=str(body / "body.md"),
        forms_docx_path=str(d / "06_fill/forms/forms.docx") if paths.get("forms", True) else "",
        deviation_docx_path=str(d / "06_fill/deviation/deviation.docx") if paths.get("deviation") else "",
        commercial_docx_path=str(d / "06_fill/commercial/commercial.docx") if paths.get("commercial") else "",
        draft_version=version,
    )


def test_assemble_replaces_anchored_sections_in_template_order(tmp_path: Path, monkeypatch):
    """商务/技术按锚标题区间替换（非追加）：壳不重复、顺序跟模板、正文进锚点。"""
    state = _state(tmp_path, monkeypatch, forms=True, commercial=True, deviation=False)
    updates = asm.assemble_node(state)
    doc = Document(updates["draft_docx_path"])
    texts = [p.text for p in doc.paragraphs]

    # 各锚标题只出现一次（无重复壳）
    for h in ("投标函", "商务部分", "技术部分"):
        assert texts.count(h) == 1, (h, texts)
    # 填充内容在位
    assert "公司：测试投标人公司" in texts            # forms 底稿
    assert "业绩：智慧城市监测平台合同" in texts        # commercial 商务区间（替换）
    # 技术部分空壳被正文替换
    assert "（技术方案格式自定）" not in texts
    assert "总体思路内容。" in texts
    # 顺序跟模板：商务内容 < 技术部分标题 < 正文内容
    assert texts.index("业绩：智慧城市监测平台合同") < texts.index("技术部分")
    assert texts.index("技术部分") < texts.index("总体思路内容。")


def test_assemble_appends_only_missing_deviation_range(tmp_path: Path, monkeypatch):
    """底稿无偏离表区间 -> 仅追加填充文档中的偏离表区间，不整本拼接。"""
    state = _state(tmp_path, monkeypatch, forms=True, commercial=False, deviation=True)
    updates = asm.assemble_node(state)
    doc = Document(updates["draft_docx_path"])
    texts = [p.text for p in doc.paragraphs]

    assert texts.count("偏离表") == 1
    assert "偏离说明：全部无偏离" in texts
    assert texts.count("投标函") == 1               # deviation 整本未拼接进来


def test_assemble_fallback_without_heading_styles(tmp_path: Path, monkeypatch):
    """无标题样式的底稿：正文尾部追加 + commercial 兜底去重追加，不崩溃。"""
    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    body = d / "05_body"
    body.mkdir(parents=True, exist_ok=True)
    (body / "body.md").write_text("# 1 总体思路\n\n总体思路内容。", encoding="utf-8")

    plain = Document()                                # 无 Heading 样式
    plain.add_paragraph("封面页")
    plain.add_paragraph("商务部分")
    plain.add_paragraph("（此处填写）")
    forms_p = d / "06_fill" / "forms" / "forms.docx"
    forms_p.parent.mkdir(parents=True, exist_ok=True)
    plain.save(forms_p)

    comm = Document()                                 # 整本无标题 + 商务已填
    comm.add_paragraph("封面页")
    comm.add_paragraph("商务部分")
    comm.add_paragraph("（此处填写）")
    comm.add_paragraph("业绩：合同一份")
    comm_p = d / "06_fill" / "commercial" / "commercial.docx"
    comm_p.parent.mkdir(parents=True, exist_ok=True)
    comm.save(comm_p)

    state = BidState(
        run_id="run-1", body_md_path=str(body / "body.md"),
        forms_docx_path=str(forms_p), commercial_docx_path=str(comm_p),
    )
    updates = asm.assemble_node(state)
    doc = Document(updates["draft_docx_path"])
    texts = [p.text for p in doc.paragraphs]
    assert "总体思路内容。" in texts                   # 正文尾部追加
    assert "业绩：合同一份" in texts                   # commercial 兜底追加
    assert texts.count("封面页") == 1                  # 壳文本去重


def test_assemble_version_increments(tmp_path: Path, monkeypatch):
    state = _state(tmp_path, monkeypatch, version=1, forms=True, commercial=False, deviation=False)
    updates = asm.assemble_node(state)
    assert Path(updates["draft_docx_path"]).name == "标书草稿_v2.docx"
    assert (run_dir(state) / "07_draft" / "latest.txt").read_text(encoding="utf-8") == "2"


def test_assemble_concatenates_parts_in_template_order(tmp_path: Path, monkeypatch):
    """parts.yaml 存在时:四份 part 按文档原序拼接,technical 注入 body,
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
    (body / "body.md").write_text("# 1 总体思路\n\n总体思路内容。", encoding="utf-8")

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
        deviation_docx_path=_filled("deviation", "偏离已填标记"),
        commercial_docx_path="",                      # commercial 跳过 -> 用原始 part
    )
    updates = asm.assemble_node(state)
    texts = [p.text for p in Document(updates["draft_docx_path"]).paragraphs if p.text.strip()]
    joined = "\n".join(texts)
    # 顺序:前言(commercial 原始 part) < forms 已填 < technical body < deviation 已填
    assert joined.index("第五章 响应文件组成") < joined.index("一、磋商响应声明")
    assert joined.index("表单已填标记") < joined.index("总体思路内容")
    assert joined.index("总体思路内容") < joined.index("偏离已填标记")
    assert "三、保证金 模板正文。" in joined                        # 跳过桶保留模板原文
    assert "六、项目实施方案 模板正文。" not in joined               # 技术区间被 body 替换
    assert "总体思路内容" in joined                                  # body 已注入


def test_assemble_migrates_images_from_parts(tmp_path: Path, monkeypatch):
    """跨文档搬运须迁移图片关系:commercial 产物里的插图装配后 rId 须在壳包可解析。

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
    doc.add_paragraph("第五章 响应文件组成")               # 无标题前导段 -> commercial 桶
    for title in ("一、磋商响应声明", "六、项目实施方案", "七、合同条款偏离表"):
        doc.add_heading(title, level=2)
        doc.add_paragraph(f"{title} 模板正文。")
    doc.save(tpl)
    parts = st.split_template_node(
        BidState(run_id="run-1", tender_path=str(tpl), template_docx_path=str(tpl))
    )["template_parts"]

    com = Document(parts["commercial"])
    com.add_paragraph("资质证明：")
    com.add_paragraph().add_run().add_picture(BytesIO(_PNG))
    com_out = d / "06_fill" / "commercial" / "commercial.docx"
    com_out.parent.mkdir(parents=True, exist_ok=True)
    com.save(com_out)

    body = d / "05_body"
    body.mkdir(parents=True)
    (body / "body.md").write_text("# 1 总体思路\n\n内容。", encoding="utf-8")
    state = BidState(run_id="run-1", body_md_path=str(body / "body.md"),
                     template_docx_path=str(tpl), template_parts=parts,
                     commercial_docx_path=str(com_out))

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
    doc.add_paragraph("第七章 投标文件的格式")           # commercial run1
    for title in ("投标函及报价文件", "（四）法定代表人身份证明",
                  "资格证明文件", "六、项目实施方案"):
        doc.add_heading(title, level=2)
        doc.add_paragraph(f"{title} 模板正文。")
    doc.save(tpl)
    parts = st.split_template_node(
        BidState(run_id="run-1", tender_path=str(tpl), template_docx_path=str(tpl))
    )["template_parts"]
    man = st.read_parts_yaml(d)
    keys = [e["key"] for e in man["entries"]]
    assert "commercial_2" in keys                        # (四) 为 commercial 第二区间

    # 附加段独立填充产物(带标记),主 forms 用真实填充
    def _product(path: Path, marker: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        dd = Document(); dd.add_paragraph(marker); dd.save(path); return str(path)

    body = d / "05_body"; body.mkdir(parents=True)
    (body / "body.md").write_text("# 1 总体\n思路内容。", encoding="utf-8")
    filled_forms = d / "06_fill" / "forms" / "forms.docx"
    filled_forms.parent.mkdir(parents=True, exist_ok=True)
    ff = Document(parts["forms"]); ff.add_paragraph("投标函已填"); ff.save(filled_forms)

    state = BidState(run_id="run-1", body_md_path=str(body / "body.md"),
                     template_docx_path=str(tpl), template_parts=parts,
                     forms_docx_path=str(filled_forms),
                     extra_products_commercial={
                         "commercial_2": _product(d / "06_fill" / "commercial_2" /
                                                  "commercial.docx", "身份证明已填")})
    updates = asm.assemble_node(state)
    joined = "\n".join(p.text for p in Document(updates["draft_docx_path"]).paragraphs
                       if p.text.strip())
    i_chapter = joined.index("第七章")
    i_letter = joined.index("投标函已填")
    i_mid = joined.index("身份证明已填")
    i_qual = joined.index("资格证明文件 模板正文。")
    assert i_chapter < i_letter < i_mid < i_qual          # 顺序还原,不再整桶前置


def test_assemble_guards_against_bloated_product(tmp_path: Path, monkeypatch):
    """膨胀守卫:桶级产物元素数远超模板切片(harness 复述扩写)时弃用产物,
    回退原始 part——software 实测 flash 把 2 元素头切片扩成 440 元素整章。"""
    from biaoshu_gen.nodes import split_template as st

    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    ws = d / "02_template"
    ws.mkdir(parents=True)
    tpl = ws / "标书模板.docx"
    doc = Document()
    doc.add_paragraph("第七章 投标文件的格式")          # commercial 切片:2 元素
    for title in ("投标函及报价文件", "六、项目实施方案"):
        doc.add_heading(title, level=2)
        doc.add_paragraph(f"{title} 模板正文。")
    doc.save(tpl)
    parts = st.split_template_node(
        BidState(run_id="run-1", tender_path=str(tpl), template_docx_path=str(tpl))
    )["template_parts"]

    bloated = d / "06_fill" / "commercial" / "commercial.docx"   # 产物:复述扩写
    bloated.parent.mkdir(parents=True, exist_ok=True)
    bd = Document()
    bd.add_paragraph("第七章 投标文件的格式")
    for i in range(60):                                          # 61 元素 >> 2*3+30
        bd.add_paragraph(f"复述内容{i}")
    bd.save(bloated)

    body = d / "05_body"; body.mkdir(parents=True)
    (body / "body.md").write_text("# 1 总体\n思路内容。", encoding="utf-8")
    state = BidState(run_id="run-1", body_md_path=str(body / "body.md"),
                     template_docx_path=str(tpl), template_parts=parts,
                     commercial_docx_path=str(bloated))
    updates = asm.assemble_node(state)
    texts = [p.text for p in Document(updates["draft_docx_path"]).paragraphs]
    assert not any("复述内容" in t for t in texts)               # 产物被守卫拒绝
    assert sum(1 for t in texts if t == "第七章 投标文件的格式") == 1  # 原始切片就位


def test_assemble_demotes_body_headings_to_anchor_level(tmp_path: Path, monkeypatch):
    """#70:技术节注入的正文标题须降级到锚点层级——锚是 H2 时正文 H1→H2、H2→H3,
    保证目录层级不断裂(正文 H1 曾直接成章,与宿主标题平级)。"""
    from biaoshu_gen.nodes import split_template as st

    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    ws = d / "02_template"
    ws.mkdir(parents=True)
    tpl = ws / "标书模板.docx"
    doc = Document()
    doc.add_paragraph("第五章 响应文件组成")
    for title in ("一、磋商响应声明", "六、项目实施方案", "七、合同条款偏离表"):
        doc.add_heading(title, level=2)
        doc.add_paragraph(f"{title} 模板正文。")
    doc.save(tpl)
    parts = st.split_template_node(
        BidState(run_id="run-1", tender_path=str(tpl), template_docx_path=str(tpl))
    )["template_parts"]

    body = d / "05_body"
    body.mkdir(parents=True)
    (body / "body.md").write_text(
        "# 1 总体思路\n\n总体内容。\n\n## 1.1 实施要点\n\n要点内容。", encoding="utf-8")
    state = BidState(run_id="run-1", body_md_path=str(body / "body.md"),
                     template_docx_path=str(tpl), template_parts=parts,
                     forms_docx_path="", deviation_docx_path="", commercial_docx_path="")
    updates = asm.assemble_node(state)
    doc2 = Document(updates["draft_docx_path"])
    styles = {p.text.strip(): p.style.name for p in doc2.paragraphs if p.text.strip()}
    assert styles["1 总体思路"] == "Heading 2"          # H1 → 锚点级
    assert styles["1.1 实施要点"] == "Heading 3"        # H2 → 锚点+1
    assert styles["六、项目实施方案"] == "Heading 2"     # 宿主锚点不动
