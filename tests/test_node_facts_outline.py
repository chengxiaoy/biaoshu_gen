import json
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from biaoshu_gen.nodes import facts as facts_mod
from biaoshu_gen.nodes import outline as outline_mod
from biaoshu_gen.schemas import GlobalFacts, Outline
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


def _no_llu_factory():
    """任何调用都会炸的工厂--用于断言'已存在文件时不调 LLM'。"""
    def make(*a, **kw):
        raise AssertionError("不应调用 LLM")
    return make


def test_facts_existing_yaml_wins(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1")
    p = run_dir(state) / "03_facts.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("schedule: 90 天\nstaffing: 项目经理 1 名\n", encoding="utf-8")
    monkeypatch.setattr(facts_mod, "make_agent", _no_llu_factory())
    updates = facts_mod.facts_node(state)
    assert updates["facts"].schedule == "90 天"


def test_facts_generates_when_missing(tmp_path: Path, monkeypatch, fake_agent_factory):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1", metadata=None, scoring=None)
    monkeypatch.setattr(facts_mod, "make_agent",
                        fake_agent_factory({GlobalFacts: {"schedule": "60 天"}}))
    updates = facts_mod.facts_node(state)
    assert updates["facts"].schedule == "60 天"
    assert (run_dir(state) / "03_facts.yaml").exists()


def test_outline_existing_yaml_wins(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1")
    p = run_dir(state) / "04_outline.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("sections:\n- title: 总体方案\n  target_words: 800\ntotal_words: 800\n",
                 encoding="utf-8")
    monkeypatch.setattr(outline_mod, "make_agent", _no_llu_factory())
    updates = outline_mod.outline_node(state)
    assert updates["outline"].sections[0].title == "总体方案"


def test_outline_generates_with_template_context(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tpl = tmp_path / "template.md"
    tpl.write_text("# 模板\n- 技术方案\n", encoding="utf-8")
    state = BidState(run_id="run-1", template_md_path=str(tpl))
    captured = {}

    # pydantic-ai 1.107.5 适配：单一 output_type 工厂，无条件返回 ModelResponse
    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            captured["last_prompt"] = _last_user_content(messages)
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            return ModelResponse(parts=[ToolCallPart(
                tool_name=tool_name,
                args=json.dumps({"sections": [{"title": "总体方案"}], "total_words": 500}),
            )])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)
    monkeypatch.setattr(outline_mod, "make_agent", make)

    updates = outline_mod.outline_node(state)
    assert updates["outline"].sections[0].title == "总体方案"
    assert "# 模板" in captured["last_prompt"]        # 模板上下文进入 prompt
    assert (run_dir(state) / "04_outline.yaml").exists()


def test_outline_prefers_edited_facts_yaml(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1", facts=GlobalFacts(schedule="90 天", staffing="5 人"))
    p = run_dir(state) / "03_facts.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("schedule: 120 天\nstaffing: 8 人\n", encoding="utf-8")
    captured = {}

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            captured["last_prompt"] = _last_user_content(messages)
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            return ModelResponse(parts=[ToolCallPart(
                tool_name=tool_name,
                args=json.dumps({"sections": [{"title": "总体方案"}], "total_words": 500}),
            )])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)
    monkeypatch.setattr(outline_mod, "make_agent", make)

    updates = outline_mod.outline_node(state)
    assert updates["outline"].sections[0].title == "总体方案"
    assert "120 天" in captured["last_prompt"]         # 用户编辑的 03_facts.yaml 覆盖 state.facts
    assert "90 天" not in captured["last_prompt"]      # 陈旧的 state.facts 不得流入 prompt


def test_outline_falls_back_to_state_facts(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1", facts=GlobalFacts(schedule="90 天", staffing="5 人"))
    captured = {}

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            captured["last_prompt"] = _last_user_content(messages)
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            return ModelResponse(parts=[ToolCallPart(
                tool_name=tool_name,
                args=json.dumps({"sections": [{"title": "总体方案"}], "total_words": 500}),
            )])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)
    monkeypatch.setattr(outline_mod, "make_agent", make)

    outline_mod.outline_node(state)                    # 无 03_facts.yaml -> 回退 state.facts
    assert "90 天" in captured["last_prompt"]
