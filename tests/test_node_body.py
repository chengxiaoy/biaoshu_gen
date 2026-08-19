import json
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from biaoshu_gen.nodes import body as body_mod
from biaoshu_gen.nodes import body_review as br_mod
from biaoshu_gen.schemas import (
    BodyReviewReport, GlobalFacts, Outline, OutlineNode, SectionBody,
)
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


def _leaf(i: str, title: str, target: int = 20, desc: str = "") -> OutlineNode:
    return OutlineNode(id=i, title=title, target_words=target, description=desc)


def _outline() -> Outline:
    return Outline(sections=[
        OutlineNode(id="1", title="总体方案", children=[
            _leaf("1.1", "背景现状", desc="架构背景"),
            _leaf("1.2", "建设思路", desc="技术路线")]),
        OutlineNode(id="2", title="实施方案", children=[
            _leaf("2.1", "进度安排", desc="里程碑"),
            _leaf("2.2", "质量保障", desc="质量体系")]),
    ], total_words=80)


def _kb_dir(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    kb.mkdir(exist_ok=True)
    (kb / "简介.md").write_text("公司具备 CMMI5 与等保三级案例。", encoding="utf-8")
    return kb


def _state(tmp_path: Path, **updates) -> BidState:
    return BidState(
        run_id="run-1", kb_dir=str(_kb_dir(tmp_path)),
        facts=GlobalFacts(schedule="90 天", staffing="5 人"),
        outline=_outline(), **updates,
    )


def _factory(content: str, captured: list | None = None):
    """单一 output_type 的假工厂：返回固定 SectionBody 内容，可选捕获 prompt。"""

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            if captured is not None:
                captured.append(_last_user_content(messages))
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            out = {"title": "占位", "content": content}
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=json.dumps(out))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)
    return make


def _review_factory(report: dict, captured: list | None = None):
    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            if captured is not None:
                captured.append(_last_user_content(messages))
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=json.dumps(report))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)
    return make


OK_CONTENT = "内容达标" * 5          # 20 字，命中 20±20% 区间


def test_body_writes_leaf_files_and_tree_md(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    captured: list = []
    monkeypatch.setattr(body_mod, "make_agent", _factory(OK_CONTENT, captured))
    updates = body_mod.body_node(state)

    d = run_dir(state) / "05_body"
    for name in ("1.1-背景现状.md", "1.2-建设思路.md", "2.1-进度安排.md", "2.2-质量保障.md"):
        assert (d / name).exists(), name
    body_md = (d / "body.md").read_text(encoding="utf-8")
    assert "# 总体方案" in body_md and "## 背景现状" in body_md and "## 质量保障" in body_md
    assert body_md.index("背景现状") < body_md.index("进度安排")   # 按目录顺序拼装
    # 全书目录上下文进入每个叶子 prompt；描述进入各自 prompt
    assert all("1 总体方案" in p and "2.2 质量保障" in p for p in captured)
    assert any("架构背景" in p for p in captured)     # 各自的写作要点进入对应 prompt
    assert updates["body_feedback"] == "" and updates["body_fix_sections"] == []


def test_body_selective_fix_only_rewrites_problem_leaves(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(body_mod, "make_agent", _factory("旧内容" * 7))     # 21 字，亦在区间
    body_mod.body_node(state)
    d = run_dir(state) / "05_body"
    old_11 = (d / "1.1-背景现状.md").read_text(encoding="utf-8")

    fix_state = _state(tmp_path, body_fix_sections=["2.1"], body_feedback="[2.1] 补充进度计划")
    monkeypatch.setattr(body_mod, "make_agent", _factory("修复内容" * 5))
    body_mod.body_node(fix_state)

    assert "修复内容" in (d / "2.1-进度安排.md").read_text(encoding="utf-8")
    assert (d / "1.1-背景现状.md").read_text(encoding="utf-8") == old_11   # 未修复小节保持不动
    assert "修复内容" in (d / "body.md").read_text(encoding="utf-8")


def test_body_stale_fix_ids_fall_back_to_full_regen(tmp_path: Path, monkeypatch):
    """目录变更后 fix id 不存在 -> 整体重生成。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(body_mod, "make_agent", _factory("旧内容" * 7))
    body_mod.body_node(state)
    d = run_dir(state) / "05_body"

    stale = _state(tmp_path, body_fix_sections=["9.9.9"], body_feedback="陈旧意见")
    monkeypatch.setattr(body_mod, "make_agent", _factory("全新内容" * 5))
    body_mod.body_node(stale)

    assert "全新内容" in (d / "1.1-背景现状.md").read_text(encoding="utf-8")   # 全量重写


def test_body_review_word_violation_marks_fix_id(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(body_mod, "make_agent", _factory(OK_CONTENT))
    body_state = _state(tmp_path, **body_mod.body_node(state))
    d = run_dir(state) / "05_body"
    (d / "2.1-进度安排.md").write_text("太短", encoding="utf-8")              # 2 字，远低于下限

    monkeypatch.setattr(br_mod, "make_agent", _review_factory(
        {"passed": True, "issues": [], "problem_sections": []}))             # LLM 放行
    updates = br_mod.body_review_node(body_state)
    assert updates["body_review_passed"] is False                            # 代码侧字数否决
    assert "2.1" in updates["body_fix_sections"]
    assert any("字数不足" in i for i in updates["body_feedback"].split("；"))
    assert updates["body_review_rounds"] == 1
    assert (d / "body_review_round_1.md").exists()


def test_body_review_llm_problem_sections(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(body_mod, "make_agent", _factory(OK_CONTENT))
    body_state = _state(tmp_path, **body_mod.body_node(state))

    monkeypatch.setattr(br_mod, "make_agent", _review_factory(
        {"passed": False, "issues": ["[1.1] 与全局事实矛盾"],
         "problem_sections": ["1.1"]}))
    updates = br_mod.body_review_node(body_state)
    assert updates["body_review_passed"] is False
    assert updates["body_fix_sections"] == ["1.1"]


def test_body_review_pass(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(body_mod, "make_agent", _factory(OK_CONTENT))
    body_state = _state(tmp_path, **body_mod.body_node(state))
    monkeypatch.setattr(br_mod, "make_agent", _review_factory(
        {"passed": True, "issues": [], "problem_sections": []}))
    updates = br_mod.body_review_node(body_state)
    assert updates["body_review_passed"] is True and updates["body_fix_sections"] == []


def test_body_prefers_edited_outline_yaml(tmp_path: Path, monkeypatch):
    """用户编辑 04_outline.yaml 后，body 以文件为准（resume 不用陈旧 state.outline）。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    p = run_dir(state) / "04_outline.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "sections:\n- id: '1'\n  title: 用户修改章\n  children:\n"
        "  - id: '1.1'\n    title: 修改要点节\n    target_words: 30\n    description: 修改要点\n",
        encoding="utf-8")
    captured: list = []
    monkeypatch.setattr(body_mod, "make_agent", _factory("内容达标" * 5, captured))
    body_mod.body_node(state)
    assert "修改要点" in captured[0]                       # 编辑后的目录进入 prompt
    assert (run_dir(state) / "05_body" / "1.1-修改要点节.md").exists()
