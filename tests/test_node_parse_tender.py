import json
from pathlib import Path

from docx import Document
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from biaoshu_gen.docx_io import DocxSection
from biaoshu_gen.nodes import DEFAULT_NODES, NODE_NAMES
from biaoshu_gen.nodes import parse_tender as pt
from biaoshu_gen.nodes import structure as pt_structure
from biaoshu_gen.schemas import (
    InvalidationItems, ScoringStandards, TenderMetadata, TenderRequirements,
)
from biaoshu_gen.schemas import StructureOutline
from biaoshu_gen.state import BidState, run_dir


def _last_user_content(messages) -> str:
    last = messages[-1]
    content = getattr(last, "content", None)
    if content is None:
        content = next(
            (p.content for p in getattr(last, "parts", []) if isinstance(p, UserPromptPart)),
            "",
        )
    return str(content)


def _state(tmp_path: Path, monkeypatch) -> BidState:
    monkeypatch.chdir(tmp_path)   # data_dir 相对路径 -> tmp
    tender = tmp_path / "tender.docx"
    d = Document()
    d.add_heading("第一章 招标公告", level=1)
    d.add_paragraph("项目名称：演示项目")
    d.add_heading("第二章 技术要求", level=1)
    d.add_paragraph("系统需支持 1000 并发。")
    d.add_heading("第三章 评标办法", level=1)
    d.add_paragraph("价格分：最低价得 100 分。")
    d.save(tender)
    return BidState(run_id="run-1", tender_path=str(tender))


def test_node_names_registry():
    assert NODE_NAMES[0] == "parse_tender" and len(NODE_NAMES) == 12
    assert DEFAULT_NODES["parse_tender"] is pt.parse_tender_node
    assert callable(DEFAULT_NODES["extract_template"])  # 未实现 -> stub


def test_classify_sections_keyword_routing():
    """纯代码路由：标题命中 + 上级章节继承 + 无命中不入组。"""
    secs = [
        DocxSection(0, "(前言)", "抬头"),
        DocxSection(1, "第五章 评标办法", "x"),
        DocxSection(3, "比较和评价", "y"),          # 无关键词，继承上级"评标"
        DocxSection(3, "应予废标的情形", "z"),       # 自身命中废标 -> invalidation+scoring
        DocxSection(1, "第七章 投标文件格式", "w"),
        DocxSection(4, "投标函", "v"),               # 与其上级均无命中
    ]
    r = pt.classify_sections(secs)
    assert 2 in r["scoring"] and 3 in r["scoring"]      # 继承
    assert 4 in r["scoring"] and 4 in r["invalidation"]
    assert 5 not in r["scoring"] and 6 not in r["scoring"]
    assert 1 not in r["metadata"]                       # 前言不误入


def test_classify_sections_allows_multi_classification():
    """一节可属多组：「项目概况」既入 metadata（名称/背景/预算）也入 requirements（需求侧）。"""
    secs = [
        DocxSection(1, "第一章 项目概况",
                    "项目名称：演示项目；建设内容：1000 并发系统。"),
    ]
    r = pt.classify_sections(secs)
    assert 1 in r["metadata"] and 1 in r["requirements"]   # 双组归属


def test_parse_tender_routes_sections_by_keywords(tmp_path: Path, monkeypatch):
    state = _state(tmp_path, monkeypatch)
    captured: list[tuple[type, str]] = []
    presets: dict[type, dict] = {
        TenderMetadata: {"project_name": "演示项目", "bid_type": "服务"},
        TenderRequirements: {"tech_requirements": ["1000 并发"]},
        ScoringStandards: {"price_rules": "最低价得 100 分"},
    }

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            captured.append((output_type, _last_user_content(messages)))
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            out = presets.get(output_type, {"items": []})
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=json.dumps(out))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(pt, "make_agent", make)
    updates = pt.parse_tender_node(state)

    d = run_dir(state) / "01_parse"
    assert (d / "tender.md").exists()
    assert (d / "metadata.yaml").exists() and (d / "scoring.yaml").exists()
    assert (d / "routing.yaml").exists()               # 路由透明化
    assert updates["metadata"].project_name == "演示项目"
    assert updates["metadata"].bid_type == "服务"       # LLM 主判直接采信
    assert updates["requirements"].tech_requirements == ["1000 并发"]

    # 分节路由断言：每组抽取只看到本组章节内容（关键词路由，无 LLM 分类调用）
    called_types = {t for t, _ in captured}
    assert called_types == {TenderMetadata, TenderRequirements, ScoringStandards}
    meta_prompt = next(p for t, p in captured if t is TenderMetadata)
    assert "项目名称：演示项目" in meta_prompt and "评标办法" not in meta_prompt
    scoring_prompt = next(p for t, p in captured if t is ScoringStandards)
    assert "最低价得 100 分" in scoring_prompt and "技术要求" not in scoring_prompt


def test_parse_tender_keyword_sections_routed_to_invalidation(tmp_path: Path, monkeypatch):
    """标题含 废标/无效/扣分/偏离 的章节自动进入 invalidation 组。"""
    monkeypatch.chdir(tmp_path)
    tender = tmp_path / "t2.docx"
    d = Document()
    d.add_heading("废标条款", level=1)
    d.add_paragraph("逾期送达的投标文件将被拒收。")
    d.save(tender)
    state = BidState(run_id="run-2", tender_path=str(tender))

    presets: dict[type, dict] = {
        InvalidationItems: {"items": [{"kind": "废标项", "requirement": "不得逾期送达"}]},
    }

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            out = presets.get(output_type, {})
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=json.dumps(out))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(pt, "make_agent", make)
    updates = pt.parse_tender_node(state)
    assert updates["invalidation"].items[0].kind == "废标项"   # 关键词路由使抽取确实发生


def _state_unstructured(tmp_path: Path, monkeypatch) -> BidState:
    monkeypatch.chdir(tmp_path)
    tender = tmp_path / "ns.docx"
    d = Document()
    d.add_paragraph("第一章 采购需求")
    d.add_paragraph("系统需支持 1000 并发,提供三年质保。" * 100)   # >2000 字触发兜底
    d.add_paragraph("第二章 评标办法")
    d.add_paragraph("价格分采用低价优先法计算。" * 100)
    d.save(tender)
    return BidState(run_id="run-ns", tender_path=str(tender))


def test_parse_tender_falls_back_to_llm_rebuild(tmp_path: Path, monkeypatch):
    import yaml as _yaml
    state = _state_unstructured(tmp_path, monkeypatch)

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            if output_type is StructureOutline:
                out = {"headings": [
                    {"index": 0, "level": 1, "title": "第一章 采购需求"},
                    {"index": 2, "level": 1, "title": "第二章 评标办法"}]}
            elif output_type is TenderRequirements:
                out = {"tech_requirements": ["1000 并发"]}
            else:
                out = {}
            return ModelResponse(parts=[ToolCallPart(tool_name=tool, args=json.dumps(out))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(pt, "make_agent", make)
    monkeypatch.setattr(pt_structure, "make_agent", make)   # 兜底编排同样注入假模型
    updates = pt.parse_tender_node(state)

    d = run_dir(state) / "01_parse"
    routing = _yaml.safe_load((d / "routing.yaml").read_text(encoding="utf-8"))
    assert routing["structure_mode"] == "llm_rebuild"
    md = (d / "tender.md").read_text(encoding="utf-8")
    assert "# 第一章 采购需求" in md                        # 重建后的层级进入 tender.md
    assert updates["requirements"].tech_requirements == ["1000 并发"]


def test_parse_tender_keeps_heading_mode_when_structured(tmp_path: Path, monkeypatch):
    import yaml as _yaml
    state = _state(tmp_path, monkeypatch)                   # 3 个 Heading 的小文档
    called = {"structure": 0}

    def make(output_type, system_prompt, retries=2):
        if output_type is StructureOutline:
            called["structure"] += 1
        async def fn(messages, info: AgentInfo):
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            return ModelResponse(parts=[ToolCallPart(tool_name=tool, args=json.dumps({}))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(pt, "make_agent", make)
    monkeypatch.setattr(pt_structure, "make_agent", make)
    pt.parse_tender_node(state)
    routing = _yaml.safe_load(
        (run_dir(state) / "01_parse" / "routing.yaml").read_text(encoding="utf-8"))
    assert routing["structure_mode"] == "heading"
    assert called["structure"] == 0                         # 正常文档不发生结构重建调用


def test_classify_sections_scoring_keyword_review_factor():
    """「评审因素和标准」应入 scoring 组(真实样本验收发现的漏配)。"""
    secs = [DocxSection(1, "第二章 磋商须知", "x"),
            DocxSection(2, "附页6 评审因素和标准", "y")]
    r = pt.classify_sections(secs)
    assert 2 in r["scoring"]


def test_classify_sections_metadata_keyword_negotiation_terms():
    """竞争性磋商类文件：磋商邀请章及其子节、含截止时间的节应入 metadata 组
    (真实样本验收发现:项目名称/预算全在「第一章 磋商邀请」,旧关键词只有「投标邀请」)。"""
    secs = [DocxSection(1, "第一章 磋商邀请", "x"),
            DocxSection(2, "采购项目基本信息", "y"),
            DocxSection(3, "采购项目名称：某实训室", "z"),
            DocxSection(2, "提交首次响应文件的截止时间、磋商时间及地点", "w")]
    r = pt.classify_sections(secs)
    assert {1, 2, 3, 4} <= set(r["metadata"])


def test_classify_sections_content_fallback_scoring_table():
    """内容级兜底：评分表挂在无关键词标题下(如「保函的生效」)时,
    按正文特征(评审因素和标准/评分因素+评分标准表格)强制入 scoring 组;
    无签名的普通节不误入。"""
    secs = [
        DocxSection(1, "保函的生效",
                    "本保函自我方加盖公章之日起生效。\n\n附页6\n\n评审因素和标准\n\n"
                    "| 评分因素 | 评分标准 |\n| --- | --- |\n| 报价部分（50分） | 低价优先法计算 |"),
        DocxSection(1, "争议的解决", "协商不成的向法院起诉。"),
    ]
    r = pt.classify_sections(secs)
    assert 1 in r["scoring"]
    assert 2 not in r["scoring"]


def test_classify_sections_content_fallback_front_attachment_table():
    """metadata 内容兜底：磋商须知前附表整表挂在无关键词标题(如「第二章 磋商须知」)下,
    按表头特征(条款名称+编列内容规定)入 metadata 组;普通节不误入。
    (真实样本验收发现:真实截止时间在前附表,而磋商邀请章里只有空白模板日期。)"""
    secs = [
        DocxSection(1, "第二章 磋商须知",
                    "第一节 磋商须知前附表\n\n| 条款号 | 条款名称 | 编列内容规定 |\n"
                    "| 第18.1款 | 响应文件的递交时间和地点 | 提交首次响应文件的截止时间：2026年12月29日14:30 |"),
        DocxSection(2, "资料审查", "供应商需提供营业执照。"),
    ]
    r = pt.classify_sections(secs)
    assert 1 in r["metadata"]
    assert 2 not in r["metadata"]


def test_parse_tender_infers_bid_type_by_keywords(tmp_path: Path, monkeypatch):
    """LLM 未给出 bid_type 时，全文关键词兜底判定（工程>货物>服务 特异性序）。"""
    monkeypatch.chdir(tmp_path)
    tender = tmp_path / "t3.docx"
    d = Document()
    d.add_heading("第一章 招标公告", level=1)
    d.add_paragraph("本项目为货物类采购（服务器与存储设备），含三年维保服务。")
    d.save(tender)
    state = BidState(run_id="run-bt", tender_path=str(tender))

    presets: dict[type, dict] = {
        TenderMetadata: {"project_name": "设备项目"},   # 未给 bid_type
        TenderRequirements: {"purchase_list": ["服务器"]},
    }

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            out = presets.get(output_type, {})
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=json.dumps(out))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(pt, "make_agent", make)
    updates = pt.parse_tender_node(state)
    assert updates["metadata"].bid_type == "货物"       # 关键词兜底（「货物类采购」命中货物，
    # 且「维保服务」不覆盖——特异性序工程>货物>服务）


def test_parse_groups_extract_concurrently(tmp_path: Path, monkeypatch):
    """#69:各组抽取并发执行——全部组任务必须在彼此完成前都开工(屏障超时即败)。"""
    import threading

    from biaoshu_gen.schemas import InvalidationItems

    state = _state(tmp_path, monkeypatch)
    outputs = {TenderMetadata: TenderMetadata(project_name="A 项目"),
               TenderRequirements: TenderRequirements(tech_requirements=["R1"]),
               ScoringStandards: ScoringStandards(price_rules="B 规则"),
               InvalidationItems: InvalidationItems(items=[])}
    barrier = threading.Barrier(3, timeout=8)          # 3 组有路由任务;串行则首组超时炸

    def fake_run_sync(agent, prompt):
        barrier.wait()
        class _R:
            output = outputs[agent.output_type]
        return _R()

    class _A:
        def __init__(self, tp):
            self.output_type = tp

    monkeypatch.setattr(pt, "make_agent", lambda tp, sp, retries=2: _A(tp))
    monkeypatch.setattr(pt, "run_sync", fake_run_sync)

    updates = pt.parse_tender_node(state)
    assert updates["metadata"].project_name == "A 项目"
    assert updates["requirements"].tech_requirements == ["R1"]
    assert updates["scoring"].price_rules == "B 规则"
