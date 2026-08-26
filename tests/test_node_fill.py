from pathlib import Path

from biaoshu_gen.harness import prepare_agent_workspace
from biaoshu_gen.kb import KnowledgeBase
from biaoshu_gen.nodes import commercial as com
from biaoshu_gen.nodes import deviation_table as dev
from biaoshu_gen.nodes import fill_forms as ff
from biaoshu_gen.state import BidState, run_dir


def _fake_run(captured):
    def fake(task):
        captured.append((task.cwd, task.prompt, task.expected_outputs))
        for p in task.expected_outputs:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"fake-docx")
        return task.expected_outputs
    return fake


def _patch_fill_harness(monkeypatch, captured, mod=None):
    """fill 节点经 fill_context.run_fill_node 调用 harness，故 patch 该模块。"""
    from biaoshu_gen import fill_context
    monkeypatch.setattr(fill_context, "run_harness_task", _fake_run(captured))


def _base_state(tmp_path: Path, monkeypatch) -> BidState:
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1", kb_dir=str(tmp_path / "kb"))
    (tmp_path / "kb").mkdir(exist_ok=True)
    (tmp_path / "kb" / "简介.md").write_text("公司具备 CMMI5。", encoding="utf-8")
    (tmp_path / "kb" / "营业执照.jpg").write_bytes(b"\xff\xd8img")
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
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "a.md").write_text("具备 ISO27001。", encoding="utf-8")
    (kb_dir / "lic.jpg").write_bytes(b"\xff\xd8x")
    out = KnowledgeBase.load(kb_dir).dump_summary(tmp_path / "kb.md")
    text = out.read_text(encoding="utf-8")
    assert "ISO27001" in text and str((kb_dir / "lic.jpg").resolve()) in text


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
    {"op": "blank", "prefix": "项目名称：", "value": "演示项目"},
    {"op": "cell", "table_header": ["序号", "名称"], "row": 1, "col": 1, "value": "工业机器人"},
]}


def test_fill_forms_executes_llm_plan(tmp_path: Path, monkeypatch):
    """非 harness:LLM 直出 plan,python 经 run_fill_plan 确定性执行落盘。"""
    from docx import Document

    state = _forms_state(tmp_path, monkeypatch)
    make = _fake_fill_make([_PLAN])
    monkeypatch.setattr(ff, "make_agent", make)

    updates = ff.fill_forms_node(state)
    assert updates["forms_docx_path"].endswith(str(Path("06_fill/forms/forms.docx")))
    doc = Document(updates["forms_docx_path"])
    assert any("演示项目" in p.text for p in doc.paragraphs)      # 填空已执行
    assert doc.tables[0].cell(1, 1).text == "工业机器人"           # 表格已执行
    prompt = make.calls[0]
    assert "模板可填点地图" in prompt and "项目名称" in prompt       # 地图预注入
    assert len(make.calls) == 1                                    # 无报错不回炉


def test_fill_forms_fixes_errors_from_feedback(tmp_path: Path, monkeypatch):
    from docx import Document

    state = _forms_state(tmp_path, monkeypatch)
    bad = {"plan": [{"op": "blank", "prefix": "不存在的段落：", "value": "x"}]}
    make = _fake_fill_make([bad, _PLAN])
    monkeypatch.setattr(ff, "make_agent", make)

    updates = ff.fill_forms_node(state)
    assert len(make.calls) == 2
    assert "报错" in make.calls[1]                                 # 第二次带执行报错反馈
    doc = Document(updates["forms_docx_path"])
    assert doc.tables[0].cell(1, 1).text == "工业机器人"            # 修正后执行成功


def test_fill_forms_raises_after_fix_rounds_exhausted(tmp_path, monkeypatch):
    state = _forms_state(tmp_path, monkeypatch)
    bad = {"plan": [{"op": "blank", "prefix": "不存在的段落：", "value": "x"}]}
    make = _fake_fill_make([bad])
    monkeypatch.setattr(ff, "make_agent", make)

    import pytest
    with pytest.raises(ff.FormsFillError):
        ff.fill_forms_node(state)
    assert len(make.calls) == 4                                    # 初次 + 3 轮修正


def test_commercial_only_harness_node_isolated_workspaces(tmp_path: Path, monkeypatch):
    """harness 家族只剩 commercial;forms/deviation 已非 harness 化(各有独立测试)。"""
    state = _with_template(tmp_path, monkeypatch, text="商务部分\n偏离表")
    captured = []
    _patch_fill_harness(monkeypatch, captured)
    u3 = com.commercial_node(state)

    assert u3["commercial_docx_path"].endswith("commercial.docx")
    assert len({c[0] for c in captured}) == 1
    ws = run_dir(state) / "06_fill" / "commercial"
    assert (ws / "tender.md").exists() and (ws / "kb.md").exists()
    assert "CMMI5" in (ws / "kb.md").read_text(encoding="utf-8")
    assert (ws / "scoring.yaml").exists()


def test_deviation_skipped_without_template(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _base_state(tmp_path, monkeypatch)
    assert dev.deviation_table_node(state) == {"deviation_docx_path": ""}


def test_commercial_skipped_without_template(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _base_state(tmp_path, monkeypatch)
    assert com.commercial_node(state) == {"commercial_docx_path": ""}


def test_commercial_skipped_when_template_no_commercial(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _with_template(tmp_path, monkeypatch, text="偏离表")
    assert com.commercial_node(state) == {"commercial_docx_path": ""}


def test_commercial_fills_template_with_commercial(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _with_template(tmp_path, monkeypatch, text="商务部分\n业绩证明文件")
    captured = []
    _patch_fill_harness(monkeypatch, captured)
    updates = com.commercial_node(state)
    assert updates["commercial_docx_path"].endswith("commercial.docx")
    assert len(captured) == 1
    assert "商务部分" in captured[0][1]                  # prompt 强调按模板商务部分填写
    assert "不得删减" not in captured[0][1] or "标书模板.docx" in captured[0][1]


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
    """模板地图/facts/图片路径预注入 prompt，harness 无需读文件探查。"""
    monkeypatch.chdir(tmp_path)
    from docx import Document
    state = _base_state(tmp_path, monkeypatch)
    tpl = tmp_path / "标书模板.docx"
    d = Document()
    d.add_paragraph("项目名称：＿＿＿")
    d.add_paragraph("商务部分")
    d.save(tpl)
    state = state.model_copy(update={"template_docx_path": str(tpl)})

    captured = []
    _patch_fill_harness(monkeypatch, captured)
    com.commercial_node(state)
    prompt = captured[0][1]
    assert "模板可填点地图" in prompt and "项目名称" in prompt   # 地图已注入
    assert "facts.yaml 全文" in prompt and "90 天" in prompt    # facts 已注入
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
    assert "项目名称×1" in summary and "投标人×1" in summary


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
    plan = {"plan": [{"op": "blank", "prefix": "项目名称：", "value": "演示项目"}]}
    make = _fake_fill_make([plan])
    monkeypatch.setattr(ff, "make_agent", make)

    updates = ff.fill_forms_node(state)
    texts = [p.text for p in Document(updates["forms_docx_path"]).paragraphs if p.text.strip()]
    assert "投标函（格式）" in texts                              # 来自 part


def test_fill_forms_falls_back_to_whole_template_without_part(tmp_path: Path, monkeypatch):
    from docx import Document

    state = _forms_state(tmp_path, monkeypatch)
    state = state.model_copy(update={"template_parts": {}})     # 无 parts(老 run)
    make = _fake_fill_make([_PLAN])
    monkeypatch.setattr(ff, "make_agent", make)

    updates = ff.fill_forms_node(state)
    doc = Document(updates["forms_docx_path"])
    assert doc.tables[0].cell(1, 1).text == "工业机器人"          # 整模板为底稿执行成功


def test_fill_forms_fix_round_replays_on_fresh_base(tmp_path, monkeypatch):
    """修复轮重放须从预填底稿重置:否则首轮成功的 blank 在改写后的底稿上
    找不到下划线,报错永不收敛(真实样本 E2E 踩过:轮次耗尽仍 2 条错)。"""
    from docx import Document

    state = _forms_state(tmp_path, monkeypatch)
    good = {"op": "blank", "prefix": "项目名称：", "value": "演示项目"}
    bad = {"op": "blank", "prefix": "不存在的段落：", "value": "x"}
    fixed = {"op": "cell", "table_header": ["序号", "名称"], "row": 1, "col": 1,
             "value": "工业机器人"}
    # 第一轮:好 op + 坏 op;第二轮:同一个好 op + 修正 op(LLM 只删坏条目)
    make = _fake_fill_make([{"plan": [good, bad]}, {"plan": [good, fixed]}])
    monkeypatch.setattr(ff, "make_agent", make)

    updates = ff.fill_forms_node(state)
    assert len(make.calls) == 2
    doc = Document(updates["forms_docx_path"])
    assert any("演示项目" in p.text for p in doc.paragraphs)     # 好 op 重放成功
    assert doc.tables[0].cell(1, 1).text == "工业机器人"          # 修正 op 执行成功
