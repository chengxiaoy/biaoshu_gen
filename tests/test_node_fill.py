from pathlib import Path

from biaoshu_gen.harness import prepare_agent_workspace
from biaoshu_gen.ledger import build
from biaoshu_gen.nodes import deviation_table as dev
from biaoshu_gen.nodes import fill_forms as ff
from biaoshu_gen.state import BidState, run_dir


def _fake_run(captured):
    """假 harness：只记录调用，不动产物（程序化路径已生成真实 docx）。"""
    def fake(task):
        captured.append((task.cwd, task.prompt, task.expected_outputs))
        return task.expected_outputs
    return fake


def _patch_fill_harness(monkeypatch, captured=None):
    """patch fill_forms 的 harness 兜底(kb 有图时必触发);返回 captured 调用记录列表。"""
    if captured is None:
        captured = []
    monkeypatch.setattr(ff, "run_harness_task", _fake_run(captured))
    return captured


def _base_state(tmp_path: Path, monkeypatch) -> BidState:
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1", kb_dir=str(tmp_path / "kb"))
    ent = tmp_path / "kb" / "1、企业信息"
    ent.mkdir(parents=True, exist_ok=True)
    (ent / "简介.md").write_text("公司具备 CMMI5。", encoding="utf-8")
    (ent / "营业执照.jpg").write_bytes(b"\xff\xd8img")
    parse = run_dir(state) / "01_parse"
    parse.mkdir(parents=True)
    (parse / "tender.md").write_text("# 招标公告", encoding="utf-8")
    (parse / "invalidation.yaml").write_text("items: []\n", encoding="utf-8")
    (parse / "metadata.yaml").write_text("project_name: 演示\n", encoding="utf-8")
    (parse / "requirements.yaml").write_text("tech_requirements: []\n", encoding="utf-8")
    (parse / "scoring.yaml").write_text("technical_rules: []\n", encoding="utf-8")
    (run_dir(state) / "03_facts.yaml").write_text("schedule: 90 天\n", encoding="utf-8")
    return state


def test_dump_summary_contains_text_and_images(tmp_path: Path):
    from biaoshu_gen.ledger import build

    kb_dir = tmp_path / "kb"
    ent = kb_dir / "1、企业信息"
    ent.mkdir(parents=True)
    (ent / "a.md").write_text("具备 ISO27001。", encoding="utf-8")
    (ent / "lic.jpg").write_bytes(b"\xff\xd8x")
    out = build(kb_dir).dump(tmp_path / "kb.md")
    text = out.read_text(encoding="utf-8")
    assert "ISO27001" in text and str((ent / "lic.jpg").resolve()) in text


def _with_template(tmp_path: Path, monkeypatch, text: str = "偏离表") -> BidState:
    """构造含指定段落（默认偏离表）的响应模板（判定依据为响应模板）。"""
    from docx import Document
    state = _base_state(tmp_path, monkeypatch)
    tpl = tmp_path / "标书模板.docx"
    d = Document()
    d.add_paragraph(text)
    d.save(tpl)
    return state.model_copy(update={"template_docx_path": str(tpl)})


def _fake_fill_make(responses: list[dict]):
    """按调用次序返回预设 FormsFill JSON 的假 agent 工厂;记录收到的 prompt。"""
    import json as _json

    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    calls: list[str] = []

    def make(output_type, system_prompt, retries=2):
        def fn(messages, info: AgentInfo):
            calls.append(messages[-1].parts[-1].content)
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            payload = responses[min(len(calls) - 1, len(responses) - 1)]
            return ModelResponse(parts=[ToolCallPart(tool_name=tool, args=_json.dumps(payload))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    make.calls = calls
    return make


def _forms_state(tmp_path: Path, monkeypatch) -> BidState:
    """含投标函填空与一览表的响应模板(facts 已 mock 企业资料)。"""
    monkeypatch.chdir(tmp_path)
    from docx import Document

    tpl = tmp_path / "标书模板.docx"
    d = Document()
    d.add_paragraph("项目名称：__________")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "序号"
    t.cell(0, 1).text = "名称"
    d.save(tpl)
    state = _base_state(tmp_path, monkeypatch)
    from biaoshu_gen.business import ensure_business_fields
    ensure_business_fields(state)
    return state.model_copy(update={"template_docx_path": str(tpl)})


_PLAN = {"plan": [
    {"op": "label", "label": "项目名称：", "value": "演示项目"},
    {"op": "cell", "table_header": ["序号", "名称"], "row": 1, "col": 1, "value": "工业机器人"},
]}


def test_fill_forms_executes_llm_plan(tmp_path: Path, monkeypatch):
    """LLM 直出 plan,python 经 run_fill_plan 确定性执行落盘;kb 有图时仍触发一次
    harness 插图 pass(feedback #86 终版:插图位置由 harness 自主决定)。"""
    from docx import Document

    state = _forms_state(tmp_path, monkeypatch)
    make = _fake_fill_make([_PLAN])
    monkeypatch.setattr(ff, "make_agent", make)
    captured = _patch_fill_harness(monkeypatch)

    updates = ff.fill_forms_node(state)
    assert updates["forms_docx_path"].endswith(str(Path("06_fill/forms/forms.docx")))
    doc = Document(updates["forms_docx_path"])
    assert any("演示项目" in p.text for p in doc.paragraphs)      # 填空已执行
    assert doc.tables[0].cell(1, 1).text == "工业机器人"           # 表格已执行
    prompt = make.calls[0]
    assert "模板可填点地图" in prompt and "项目名称" in prompt       # 地图预注入
    assert len(make.calls) == 1                                    # 无报错不回炉
    assert len(captured) == 1 and "insert_picture_after" in captured[0][1]  # kb 有图:插图 pass 照跑


def test_fill_forms_execution_errors_logged_not_harnessed(tmp_path, monkeypatch):
    """执行报错 -> 不回炉重出 plan,也不交 harness(填 阶段 harness 只插图):报错 op 记
    error.log 供人工补,产物保留已执行成果;插图 pass 照跑但 prompt 不含报错清单。"""
    state = _forms_state(tmp_path, monkeypatch)
    bad = {"plan": [{"op": "label", "label": "不存在的段落：", "value": "x"},
                    {"op": "label", "label": "项目名称：", "value": "演示项目"}]}
    make = _fake_fill_make([bad])
    monkeypatch.setattr(ff, "make_agent", make)
    captured = _patch_fill_harness(monkeypatch)

    updates = ff.fill_forms_node(state)
    assert len(make.calls) == 1                                    # plan 通道单次,无修正轮
    assert len(captured) == 1                                      # harness 只发起插图 pass
    prompt = captured[0][1]
    assert "插图" in prompt and "不存在的段落" not in prompt        # 纯插图任务,无报错清单
    assert updates["forms_docx_path"] and Path(updates["forms_docx_path"]).exists()
    from docx import Document as _D
    assert any("演示项目" in p.text for p in _D(updates["forms_docx_path"]).paragraphs)
    errlog = run_dir(state) / "06_fill" / "fill_forms.error.log"
    assert "不存在的段落" in errlog.read_text(encoding="utf-8")   # 报错 op 留痕供人工补


def test_fill_forms_plan_failure_logged_keeps_product(tmp_path, monkeypatch):
    """plan 两次校验均失败 -> 记 error.log 放行(产物=预填底稿);插图 pass 照常发起,
    不做全量兜底填写(harness 只插图)。

    失败取「空 plan」(过 Pydantic、被节点 _validate 拒)而非非法 op——FillOp.op
    收紧为 Literal 后,非法值在 pydantic-ai 输出校验层抛 UnexpectedModelBehavior,
    会被 models.run_sync 当瞬态错误指数退避 70s,单测会假死。"""
    state = _forms_state(tmp_path, monkeypatch)
    bad = {"plan": []}
    make = _fake_fill_make([bad, bad])                             # 两次都非法
    monkeypatch.setattr(ff, "make_agent", make)
    captured = _patch_fill_harness(monkeypatch)

    updates = ff.fill_forms_node(state)
    assert len(make.calls) == 2                                    # 校验重试一次后放弃
    assert len(captured) == 1                                      # 插图 pass 照跑
    assert "插图" in captured[0][1] and "全量" not in captured[0][1]
    assert updates["forms_docx_path"] and Path(updates["forms_docx_path"]).exists()
    errlog = run_dir(state) / "06_fill" / "fill_forms.error.log"
    assert "程序化填写失败" in errlog.read_text(encoding="utf-8")


def test_fill_forms_execution_and_picture_failures_both_logged(tmp_path, monkeypatch):
    """报错 op 与插图 pass 失败同 run 发生:error.log 合并记录两项(覆盖写,须一次收齐),
    产物保留程序化成果。"""
    state = _forms_state(tmp_path, monkeypatch)
    bad = {"plan": [{"op": "label", "label": "不存在的段落：", "value": "x"}]}
    monkeypatch.setattr(ff, "make_agent", _fake_fill_make([bad]))

    def boom(task):
        raise RuntimeError("HARNESS_API_KEY 未配置")
    monkeypatch.setattr(ff, "run_harness_task", boom)

    updates = ff.fill_forms_node(state)
    assert Path(updates["forms_docx_path"]).exists()               # 产物保留
    text = (run_dir(state) / "06_fill" / "fill_forms.error.log").read_text(encoding="utf-8")
    assert "不存在的段落" in text and "插图 pass 失败" in text     # 两项合并留痕


def test_deviation_skipped_without_template(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _base_state(tmp_path, monkeypatch)
    assert dev.deviation_table_node(state) == {"deviation_docx_path": ""}


def test_prepare_agent_workspace_base_inputs(tmp_path: Path, monkeypatch):
    state = _base_state(tmp_path, monkeypatch)
    tpl = tmp_path / "标书模板.docx"
    tpl.write_bytes(b"tpl")
    state = state.model_copy(update={"template_docx_path": str(tpl)})
    (tmp_path / "extra.yaml").write_text("e: 1", encoding="utf-8")
    ws = prepare_agent_workspace(state, "06_fill/forms", [
        (tmp_path / "extra.yaml", "extra.yaml")])
    for name in ("tender.md", "invalidation.yaml", "标书模板.docx", "kb.md", "extra.yaml",
                 "fill_skill.py"):
        assert (ws / name).exists(), name


def test_fill_prompts_preinject_context(tmp_path: Path, monkeypatch):
    """模板地图/facts/企业信息摘要/图片路径预注入 prompt，harness 兜底无需读文件探查。"""
    state = _forms_state(tmp_path, monkeypatch)
    bad = {"plan": [{"op": "label", "label": "不存在的段落：", "value": "x"}]}
    monkeypatch.setattr(ff, "make_agent", _fake_fill_make([bad]))
    captured = _patch_fill_harness(monkeypatch)

    ff.fill_forms_node(state)
    prompt = captured[0][1]
    assert "模板可填点地图" in prompt and "项目名称" in prompt   # 地图已注入
    assert "facts.yaml" in prompt and "某某科技" in prompt       # facts(企业资料/模板字段)已注入
    assert "90 天" not in prompt                                 # schedule 等正文向字段被精简出 fill prompt
    assert "企业信息摘要" in prompt and "CMMI5" in prompt       # 企业信息摘要已注入
    assert "营业执照.jpg" in prompt                              # 图片绝对路径已注入


def test_prefill_known_fills_deterministic_values(tmp_path: Path, monkeypatch):
    """确定值（项目名称/编号/投标人等）由代码预填进模板副本，prompt 标注勿重复。"""
    monkeypatch.chdir(tmp_path)
    from docx import Document
    state = _base_state(tmp_path, monkeypatch)
    tpl = tmp_path / "标书模板.docx"
    d = Document()
    for label in ("项目名称：", "项目编号：", "投标人（签章）：", "法定代表人：", "采购人名称："):
        p = d.add_paragraph()
        p.add_run(label)
        blank = p.add_run("        ")
        blank.underline = True
    d.add_paragraph("商务部分")
    d.save(tpl)
    state = state.model_copy(update={"template_docx_path": str(tpl)})
    # facts 带 template_fields 与企业资料
    from biaoshu_gen.business import ensure_business_fields
    ensure_business_fields(state)
    fp = run_dir(state) / "03_facts.yaml"
    fp.write_text(fp.read_text(encoding="utf-8")
                  + 'template_fields:\n  项目名称: 演示项目\n  项目编号: DEMO-001\n  采购人名称: 某某局\n',
                  encoding="utf-8")

    from biaoshu_gen.fill_context import prefill_known
    from docx import Document as D
    doc = D(str(tpl))
    summary = prefill_known(doc, state)
    doc.save(tpl)
    d2 = D(str(tpl))
    texts = [p.text for p in d2.paragraphs]
    assert "项目名称：演示项目" in texts
    assert "项目编号：DEMO-001" in texts
    assert "采购人名称：某某局" in texts
    assert any(t.startswith("投标人（签章）：某某科技") for t in texts)   # mock 企业名已预填
    assert any(t.startswith("法定代表人：法定代表人") for t in texts)
    assert summary["项目名称"] == 1 and summary["投标人"] == 1


def test_fill_forms_uses_part_when_present(tmp_path: Path, monkeypatch):
    """template_parts 有 forms part 时,底稿复制 part(而非整模板)。"""
    from docx import Document

    state = _forms_state(tmp_path, monkeypatch)
    part = tmp_path / "表格填写部分.docx"
    pd = Document()
    pd.add_paragraph("项目名称：__________")
    pd.add_paragraph("投标函（格式）")
    pd.save(part)
    state = state.model_copy(update={"template_parts": {"forms": str(part)}})
    plan = {"plan": [{"op": "label", "label": "项目名称：", "value": "演示项目"}]}
    make = _fake_fill_make([plan])
    monkeypatch.setattr(ff, "make_agent", make)
    captured = _patch_fill_harness(monkeypatch)

    updates = ff.fill_forms_node(state)
    texts = [p.text for p in Document(updates["forms_docx_path"]).paragraphs if p.text.strip()]
    assert "投标函（格式）" in texts                              # 来自 part
    assert len(captured) == 1 and str(captured[0][2][0]).endswith("forms.docx")  # 兜底(插图)产出产物


def test_fill_forms_falls_back_to_whole_template_without_part(tmp_path: Path, monkeypatch):
    from docx import Document

    state = _forms_state(tmp_path, monkeypatch)
    state = state.model_copy(update={"template_parts": {}})     # 无 parts(老 run)
    make = _fake_fill_make([_PLAN])
    monkeypatch.setattr(ff, "make_agent", make)
    captured = _patch_fill_harness(monkeypatch)

    updates = ff.fill_forms_node(state)
    doc = Document(updates["forms_docx_path"])
    assert doc.tables[0].cell(1, 1).text == "工业机器人"          # 整模板为底稿执行成功
    assert len(captured) == 1                                     # 插图 pass 照跑



def test_fill_nodes_soft_fail_in_pipeline(tmp_path, monkeypatch):
    """管线层软失败:节点抛异常不阻塞,写 06_fill/<节点>.error.log,输出置空。"""
    from biaoshu_gen.nodes import soft_fill_fail

    monkeypatch.chdir(tmp_path)
    state = _base_state(tmp_path, monkeypatch)

    def boom(s):
        raise RuntimeError("模拟节点崩溃")
    wrapped = soft_fill_fail("fill_forms", {"forms_docx_path": ""})(boom)
    updates = wrapped(state)
    assert updates == {"forms_docx_path": ""}
    errlog = run_dir(state) / "06_fill" / "fill_forms.error.log"
    assert errlog.exists() and "模拟节点崩溃" in errlog.read_text(encoding="utf-8")


def test_fill_forms_skips_label_ops_covered_by_prefill(tmp_path, monkeypatch):
    """预填已覆盖字段:模型仍发同义 label op 时跳过而非报错——空位已被 facts 值
    填上,再执行只会"未命中"报错;值以预填为准(VALUE_PRIORITY)。"""
    from docx import Document

    state = _forms_state(tmp_path, monkeypatch)
    fp = run_dir(state) / "03_facts.yaml"
    fp.write_text(fp.read_text(encoding="utf-8")
                  + 'template_fields:\n  项目名称: 演示项目\n', encoding="utf-8")
    plan = {"plan": [
        {"op": "label", "label": "项目名称", "value": "模型自拟名称"},
        {"op": "cell", "table_header": ["序号", "名称"], "row": 1, "col": 1, "value": "工业机器人"},
    ]}
    make = _fake_fill_make([plan])
    monkeypatch.setattr(ff, "make_agent", make)
    captured = _patch_fill_harness(monkeypatch)

    updates = ff.fill_forms_node(state)
    assert updates["forms_docx_path"]                        # 未因 miss 报错软失败
    texts = [p.text for p in Document(updates["forms_docx_path"]).paragraphs]
    assert any("演示项目" in t and "模型自拟名称" not in t for t in texts)  # 预填值生效,op 被跳过
    assert len(captured) == 1                                # 插图 pass 照跑


def test_fill_forms_drops_manual_placeholder_ops(tmp_path: Path, monkeypatch):
    """「〔待人工填写〕/〔待补〕」占位 op 被执行层丢弃(空位留给人工),正常 op 照常执行;
    prompt 已约定不发,此处兜底防模型不听话时污染产物。"""
    from docx import Document

    state = _forms_state(tmp_path, monkeypatch)
    plan = {"plan": [
        {"op": "label", "label": "项目名称：", "value": "演示项目"},          # 正常 op
        {"op": "label", "label": "投标报价：", "value": "〔待人工填写〕"},     # 占位:丢弃
        {"op": "cell", "table_header": ["序号", "名称"], "row": 1, "col": 1,
         "value": "〔待补〕"},                                              # 表格占位:丢弃
        {"op": "cell", "table_header": ["序号", "名称"], "row": 1, "col": 0,
         "value": "工业机器人"},
    ]}
    make = _fake_fill_make([plan])
    monkeypatch.setattr(ff, "make_agent", make)
    captured = _patch_fill_harness(monkeypatch)

    updates = ff.fill_forms_node(state)
    doc = Document(updates["forms_docx_path"])
    texts = [p.text for p in doc.paragraphs]
    assert any("演示项目" in t for t in texts)                            # 正常 op 已执行
    assert not any("待人工填写" in t for t in texts)
    all_cells = [c.text for t in doc.tables for r in t.rows for c in r.cells]
    assert "待补" not in "".join(all_cells) and "工业机器人" in all_cells   # 占位格未写,正常格已写
    assert len(captured) == 1                                             # 插图 pass 照跑


def test_fill_forms_hands_pictures_to_harness(tmp_path: Path, monkeypatch):
    """plan 不含 picture op(feedback #86 终版):程序化只管文字/表格;kb 有图时 plan 成功
    仍触发 harness 插图 pass,由 agent 对照文档实况自主决定插入位置(prompt 含插图任务
    与 kb 图片清单;prompt 只含插图指令)。"""
    from docx import Document

    state = _forms_state(tmp_path, monkeypatch)
    plan = {"plan": [{"op": "label", "label": "项目名称：", "value": "演示项目"}]}
    make = _fake_fill_make([plan])
    monkeypatch.setattr(ff, "make_agent", make)
    captured = _patch_fill_harness(monkeypatch)

    updates = ff.fill_forms_node(state)
    assert any("演示项目" in p.text
               for p in Document(updates["forms_docx_path"]).paragraphs)   # label 已程序化执行
    assert len(captured) == 1                                              # kb 有图触发插图 pass
    prompt = captured[0][1]
    assert "insert_picture_after" in prompt                              # 自主插图职责下放
    assert "insert_picture_into_frame" in prompt                         # #89:粘贴框进图原语
    assert "插图预匹配清单" in prompt                                     # #89:代码侧确定性锚点建议
    assert "营业执照.jpg" in prompt                                        # kb 图片清单已注入
    assert not (run_dir(state) / "06_fill" / "fill_forms.error.log").exists()


def test_picture_anchor_hints_frames_and_sections(tmp_path: Path, monkeypatch):
    """#89 插图预匹配清单:身份证类给粘贴框行锚点(图进框),信用类给小节标题锚点,
    匹配不上的标「无建议」交 agent 兜长尾。"""
    from docx import Document

    from biaoshu_gen.fill_context import picture_anchor_hints

    state = _base_state(tmp_path, monkeypatch)
    kb = tmp_path / "kb" / "1、企业信息"
    for name in ("法人身份证.png", "授权代表身份证.png", "信用中国查询.png", "生产线.png"):
        (kb / name).write_bytes(b"\x89PNG mock")

    d = Document()
    d.add_paragraph("附件2-1-2 授权委托书(格式)")
    d.add_paragraph("本授权书于      年    月    日签字生效，特此声明。")
    frame = d.add_table(rows=2, cols=1)
    frame.cell(0, 0).text = "代理人身份证正反面复印件"
    frame.cell(1, 0).text = "法定代表人（单位负责人）身份证正反面复印件"
    d.add_paragraph("附件2-5 信用信息查询")

    hints = picture_anchor_hints(state, d)
    assert "insert_picture_into_frame" in hints          # 框行建议走进框原语
    assert "代理人身份证正反面复印件" in hints            # 授权代表 → 代理人框行
    assert "法定代表人（单位负责人）身份证正反面复印件" in hints   # 法人 → 法定代表人框行
    assert "信用信息查询" in hints and "insert_picture_after" in hints  # 无框 → 标题段后
    assert "生产线.png → 无建议" in hints                 # 长尾交 agent 判断


def test_fill_forms_picture_pass_failure_logged(tmp_path: Path, monkeypatch):
    """插图 pass 兜底失败:产物保留程序化成果,error.log 记插图未完成。"""
    state = _forms_state(tmp_path, monkeypatch)
    make = _fake_fill_make([{"plan": [{"op": "label", "label": "项目名称：", "value": "演示项目"}]}])
    monkeypatch.setattr(ff, "make_agent", make)

    def boom(task):
        raise RuntimeError("HARNESS_API_KEY 未配置")
    monkeypatch.setattr(ff, "run_harness_task", boom)

    updates = ff.fill_forms_node(state)
    assert Path(updates["forms_docx_path"]).exists()                       # 产物保留
    errlog = run_dir(state) / "06_fill" / "fill_forms.error.log"
    text = errlog.read_text(encoding="utf-8")
    assert "插图" in text and "HARNESS_API_KEY 未配置" in text
