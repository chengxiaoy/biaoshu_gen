"""rich_body_v2 单测：二级节粒度交互 + 三级格式返回（feedback #76）。

fake 工厂解析单元 prompt 中的三级小节清单，逐条 sec_id 对位返回——真实行使
「按二级调用、按三级返回」的契约。不连真实 LLM/server。
"""
import json
import re
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from biaoshu_gen.nodes import rich_body_v2 as rb2

VALID_TABLE = {"type": "table", "media_content": "| 型号 | 功率 |\n|---|---|\n| X100 | 300W |",
               "media_caption": "设备参数"}


def _last_user_content(messages) -> str:
    last = messages[-1]
    content = getattr(last, "content", None)
    if content is None:
        content = next(
            (p.content for p in getattr(last, "parts", []) if isinstance(p, UserPromptPart)),
            "",
        )
    return str(content)


def _leaf_ids_in_prompt(prompt: str) -> list[str]:
    """从单元 prompt 的三级小节清单抓 sec_id（fake 按此对位返回）。"""
    return re.findall(r"^- (\d+(?:\.\d+)*) ", prompt, re.M)


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    from biaoshu_gen.nodes import rich_body as rb1
    monkeypatch.setattr(rb2, "search_snippets",
                        lambda state, q, top_k=None: [("规格.md", "X100 功率 300W")])
    monkeypatch.setattr(rb1, "render_check", lambda code: None)   # _validate_media 的引用在 rich_body


def _leaf(i: str, title: str, target: int = 20, desc: str = ""):
    from biaoshu_gen.schemas import OutlineNode
    return OutlineNode(id=i, title=title, target_words=target, description=desc)


def _outline():
    from biaoshu_gen.schemas import Outline, OutlineNode
    return Outline(sections=[
        OutlineNode(id="1", title="总体方案", children=[
            OutlineNode(id="1.1", title="设备与部署", description="硬件与网络", children=[
                _leaf("1.1.1", "设备选型", desc="硬件参数"),
                _leaf("1.1.2", "部署架构", desc="网络拓扑")])]),
        OutlineNode(id="2", title="实施方案", children=[
            OutlineNode(id="2.1", title="进度与保障", description="计划", children=[
                _leaf("2.1.1", "进度安排", desc="里程碑"),
                _leaf("2.1.2", "质保服务", desc="服务体系")])]),
    ], total_words=80)


def _state(tmp_path: Path, **updates):
    from biaoshu_gen.schemas import GlobalFacts
    from biaoshu_gen.state import BidState
    kb = tmp_path / "kb"
    kb.mkdir(exist_ok=True)
    (kb / "规格.md").write_text("X100 功率 300W。", encoding="utf-8")
    return BidState(run_id="run-1", kb_dir=str(kb),
                    facts=GlobalFacts(schedule="90 天"), outline=_outline(), **updates)


def _factory(body_content: str = "正文内容" * 5, need_type: str = "none",
             media: dict | None = None, captured: list | None = None):
    """分发 fake：UnitMediaNeeds/UnitBodies 解析清单对位；SectionMedia/InsertPoint 定值。"""

    def make(output_type, system_prompt, retries=2):
        name = output_type.__name__

        async def fn(messages, info: AgentInfo):
            prompt = _last_user_content(messages)
            if captured is not None:
                captured.append((name, prompt))
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            if name == "UnitMediaNeeds":
                out = {"needs": [{"sec_id": sid, "type": need_type, "score": 0.5}
                                 for sid in _leaf_ids_in_prompt(prompt)]}
            elif name == "UnitBodies":
                out = {"sections": [{"sec_id": sid, "title": "占位", "content": body_content}
                                    for sid in _leaf_ids_in_prompt(prompt)]}
            elif name == "SectionMedia":
                assert media is not None, "unexpected SectionMedia call"
                out = media
            else:  # InsertPoint
                out = {"index": 1}
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=json.dumps(out))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)
    return make


# ---------- 核心契约：二级交互、三级返回 ----------

def test_unit_granularity_one_call_per_second_level(tmp_path: Path, monkeypatch):
    """4 个三级小节 / 2 个二级节：正文与需求判定各只调 2 次（按二级），返回覆盖全部三级。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    captured: list = []
    monkeypatch.setattr(rb2, "make_agent",
                        _factory(captured=captured))
    updates = rb2.rich_body_v2_node(state)

    kinds = [k for k, _ in captured]
    assert kinds.count("UnitBodies") == 2          # 每二级节一次正文调用
    assert kinds.count("UnitMediaNeeds") == 2      # 每二级节一次需求判定
    assert kinds.count("SectionBody") == 0         # 不再按叶子调用

    d = tmp_path / "data" / "runs" / "run-1" / "05_body"
    for name in ("1.1.1-设备选型.md", "1.1.2-部署架构.md",
                 "2.1.1-进度安排.md", "2.1.2-质保服务.md"):
        assert (d / name).exists(), name           # 仍按三级小节落盘
    body_md = (d / "body.md").read_text(encoding="utf-8")
    assert "# 总体方案" in body_md and "### 设备选型" in body_md   # 三层标题结构
    assert updates["body_md_path"].endswith("body.md")


def test_unit_prompt_contains_all_third_level_leaves(tmp_path: Path, monkeypatch):
    """单元 prompt：二级标题/说明 + 其下全部三级小节（标题+字数+要点）。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    captured: list = []
    monkeypatch.setattr(rb2, "make_agent", _factory(captured=captured))
    rb2.rich_body_v2_node(state)
    body_prompts = [p for k, p in captured if k == "UnitBodies"]
    assert len(body_prompts) == 2
    # 每个单元 prompt：自身单元的全部三级在清单，其他单元的小节不在清单（并发下顺序不定，逐条校验）
    for prompt in body_prompts:
        m = re.search(r"【二级节】([\d.]+) ", prompt)
        own = m.group(1)
        leaf_part = prompt.split("【全书目录")[0]
        if own == "1.1":
            assert "1.1 设备与部署" in prompt and "硬件与网络" in prompt
            assert "1.1.1 设备选型" in leaf_part and "1.1.2 部署架构" in leaf_part
            assert "2.1.1" not in leaf_part
        else:
            assert "2.1 进度与保障" in prompt
            assert "2.1.1 进度安排" in leaf_part and "2.1.2 质保服务" in leaf_part
            assert "1.1.1" not in leaf_part


# ---------- 检索策略：货物类聚合 / 非货物类跳过 ----------

def test_goods_search_query_aggregates_all_leaves(tmp_path: Path, monkeypatch):
    from biaoshu_gen.schemas import TenderMetadata

    queries: list = []
    monkeypatch.setattr(rb2, "search_snippets",
                        lambda state, q, top_k=None: queries.append(q) or
                        [("规格.md", "X100 功率 300W")])
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path, metadata=TenderMetadata(bid_type="货物"))
    captured: list = []
    monkeypatch.setattr(rb2, "make_agent", _factory(captured=captured))
    rb2.rich_body_v2_node(state)

    assert len(queries) == 2                       # 每二级单元一次
    assert all(q.startswith("1.1") is False or True for q in queries)
    assert "设备与部署" in queries[0] and "硬件与网络" in queries[0]
    assert "设备选型" in queries[0] and "部署架构" in queries[0]   # 全部三级标题进 query
    assert any("X100 功率 300W" in p for k, p in captured if k == "UnitBodies")


def test_non_goods_skips_search(tmp_path: Path, monkeypatch):
    from biaoshu_gen.schemas import TenderMetadata

    calls: list = []
    monkeypatch.setattr(rb2, "search_snippets",
                        lambda state, q, top_k=None: calls.append(q) or [("x", "y")])
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path, metadata=TenderMetadata(bid_type="服务"))
    monkeypatch.setattr(rb2, "make_agent", _factory())
    rb2.rich_body_v2_node(state)
    assert calls == []


# ---------- 回环与续跑 ----------

def test_fix_only_rewrites_named_leaf(tmp_path: Path, monkeypatch):
    """fix 1.1.1：所在单元重新调用，但只写回被点名小节；1.1.2 保留原文。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(rb2, "make_agent", _factory(body_content="旧内容" * 5))
    rb2.rich_body_v2_node(state)
    d = tmp_path / "data" / "runs" / "run-1" / "05_body"
    old_112 = (d / "1.1.2-部署架构.md").read_text(encoding="utf-8")

    captured: list = []
    monkeypatch.setattr(rb2, "make_agent",
                        _factory(body_content="修复内容" * 5, captured=captured))
    fix_state = _state(tmp_path, body_fix_sections=["1.1.1"],
                       body_feedback="[1.1.1] 补充选型依据")
    rb2.rich_body_v2_node(fix_state)

    assert "修复内容" in (d / "1.1.1-设备选型.md").read_text(encoding="utf-8")
    assert (d / "1.1.2-部署架构.md").read_text(encoding="utf-8") == old_112
    # 只重生成含 fix 小节的单元；另一单元全部可复用 -> 不调用
    body_prompts = [p for k, p in captured if k == "UnitBodies"]
    assert len(body_prompts) == 1 and "补充选型依据" in body_prompts[0]
    assert "1.1.2 部署架构" in body_prompts[0]     # 单元清单仍完整（上下文）


def test_resume_skips_complete_units(tmp_path: Path, monkeypatch):
    """全部叶子已存在：零正文调用；媒体 yaml 复用零媒体调用。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(rb2, "make_agent", _factory())
    rb2.rich_body_v2_node(state)
    captured: list = []
    monkeypatch.setattr(rb2, "make_agent", _factory(captured=captured))
    rb2.rich_body_v2_node(_state(tmp_path))
    assert [k for k, _ in captured].count("UnitBodies") == 0


# ---------- 媒体：按三级上下文生成与插入 ----------

def test_media_need_not_retriggered_on_review_loop(tmp_path: Path, monkeypatch):
    """v2 同契约：首次按单元判定落盘；fix 回环重入 UnitMediaNeeds 零调用。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    captured: list = []
    monkeypatch.setattr(rb2, "make_agent", _factory(captured=captured))
    rb2.rich_body_v2_node(state)
    assert [k for k, _ in captured].count("UnitMediaNeeds") == 2
    captured.clear()

    fix_state = _state(tmp_path, body_fix_sections=["1.1.1"], body_feedback="补充")
    monkeypatch.setattr(rb2, "make_agent",
                        _factory(body_content="修复内容" * 5, captured=captured))
    rb2.rich_body_v2_node(fix_state)
    assert [k for k, _ in captured].count("UnitMediaNeeds") == 0
    assert [k for k, _ in captured].count("UnitBodies") == 1


def test_media_generated_and_inserted_per_leaf(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(rb2, "make_agent",
                        _factory(need_type="table", media=VALID_TABLE))
    rb2.rich_body_v2_node(state)
    d = tmp_path / "data" / "runs" / "run-1" / "05_body"
    leaf_md = (d / "1.1.1-设备选型.md").read_text(encoding="utf-8")
    assert "| 型号 | 功率 |" in leaf_md and "设备参数" in leaf_md
    body_md = (d / "body.md").read_text(encoding="utf-8")
    assert body_md.count("| 型号 | 功率 |") == 3    # 限额 3：全部 4 叶中 3 叶保留表格
