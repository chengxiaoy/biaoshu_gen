import json
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from biaoshu_gen.nodes import body as body_mod
from biaoshu_gen.nodes import body_review as br_mod
from biaoshu_gen.schemas import BodyReviewReport, GlobalFacts, Outline, OutlineSection, SectionBody
from biaoshu_gen.state import BidState, run_dir


def _kb_dir(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    kb.mkdir(exist_ok=True)
    (kb / "简介.md").write_text("公司具备 CMMI5 与等保三级案例。", encoding="utf-8")
    return kb


def _state(tmp_path: Path) -> BidState:
    return BidState(
        run_id="run-1", kb_dir=str(_kb_dir(tmp_path)),
        facts=GlobalFacts(schedule="90 天", staffing="5 人"),
        outline=Outline(sections=[
            OutlineSection(title="总体方案", target_words=20, key_points=["架构"]),
            OutlineSection(title="实施方案", target_words=20, key_points=["进度"]),
        ], total_words=40),
    )


def test_body_writes_sections_and_md(tmp_path: Path, monkeypatch, fake_agent_factory):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(body_mod, "make_agent", fake_agent_factory(
        {SectionBody: {"title": "占位", "content": "本章内容围绕架构展开。"}}))
    updates = body_mod.body_node(state)
    d = run_dir(state) / "05_body"
    assert (d / "01-总体方案.md").exists() and (d / "02-实施方案.md").exists()
    body_md = (d / "body.md").read_text(encoding="utf-8")
    assert "# 占位" in body_md and "本章内容" in body_md
    assert updates["body_feedback"] == ""


def test_body_feedback_injected_into_prompt(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path).model_copy(update={"body_feedback": "补充实施计划"})
    captured = {}

    # pydantic-ai 1.107.5 适配：回调须返回 ModelResponse（output tool 调用），
    # AgentInfo 无 output_type，单一 output_type 无条件返回并捕获最后一条 user 消息。
    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            last = messages[-1]
            content = getattr(last, "content", None)
            if content is None:
                content = next(
                    (p.content for p in getattr(last, "parts", []) if isinstance(p, UserPromptPart)),
                    "",
                )
            captured["prompts"] = captured.get("prompts", []) + [str(content)]
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            return ModelResponse(parts=[ToolCallPart(
                tool_name=tool_name, args=json.dumps({"title": "占位", "content": "内容"}),
            )])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)
    monkeypatch.setattr(body_mod, "make_agent", make)

    body_mod.body_node(state)
    assert all("补充实施计划" in p for p in captured["prompts"])   # 回环意见进入每章 prompt


def _prepare_body(tmp_path: Path, monkeypatch, fake_agent_factory, content: str) -> BidState:
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(body_mod, "make_agent", fake_agent_factory(
        {SectionBody: {"title": "占位", "content": content}}))
    updates = body_mod.body_node(state)
    return state.model_copy(update=updates)   # 模拟 LangGraph 合并节点返回


def test_body_review_word_violation_forces_fail(tmp_path: Path, monkeypatch, fake_agent_factory):
    state = _prepare_body(tmp_path, monkeypatch, fake_agent_factory, content="太短")   # 远低于 20 字目标下限
    monkeypatch.setattr(br_mod, "make_agent", fake_agent_factory(
        {BodyReviewReport: {"passed": True, "issues": []}}))       # LLM 放行
    updates = br_mod.body_review_node(state)
    assert updates["body_review_passed"] is False                  # 代码侧字数校验否决
    assert any("字数不足" in i for i in updates["body_feedback"].split("；"))
    assert updates["body_review_rounds"] == 1
    assert (run_dir(state) / "05_body" / "body_review_round_1.md").exists()


def test_body_review_pass(tmp_path: Path, monkeypatch, fake_agent_factory):
    # 每章实际字数需落在 20 ±20%（16~24 非空白字符）："字数合适的内容。"*3 = 24 字（含标点）
    state = _prepare_body(tmp_path, monkeypatch, fake_agent_factory, content="字数合适的内容。" * 3)
    monkeypatch.setattr(br_mod, "make_agent", fake_agent_factory(
        {BodyReviewReport: {"passed": True, "issues": []}}))
    updates = br_mod.body_review_node(state)
    assert updates["body_review_passed"] is True
