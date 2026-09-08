"""rich_body 节点单测：FunctionModel 假 agent，按 output_type 分发假输出，不连真实 LLM。

渲染校验（mermaid_render.render_check）一律 monkeypatch 掉，真实渲染只在
test_mermaid_render_live 冒烟测试里跑（本机装了 mmdc 才执行）。
"""
import json
import re
import shutil
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from biaoshu_gen.mermaid_render import render_check

from biaoshu_gen.nodes import rich_body as rb_mod
from biaoshu_gen.schemas import (
    GlobalFacts, InsertPoint, MediaNeed, Outline, OutlineNode, SectionBody, SectionMedia,
)
from biaoshu_gen.state import BidState, run_dir
from biaoshu_gen.nodes.rich_body import (
    _render_media, _validate_media, insert_media_into_content,
    overall_review_leaves, preset_table_figure,
)

VALID_TABLE = {"type": "table", "media_content": "| 型号 | 功率 |\n|---|---|\n| X100 | 300W |",
               "media_caption": "设备参数"}
VALID_FIGURE = {"type": "figure", "media_content": "flowchart TD\nA[采集] --> B[存储]",
                "media_caption": "数据流程"}


@pytest.fixture(autouse=True)
def _fake_kb_search(monkeypatch):
    """节点检索走 kb_v2（产品库），单测一律打桩，不连真 server。"""
    monkeypatch.setattr(rb_mod, "search_snippets",
                        lambda state, q, top_k=None: [("规格.md", "X100 功率 300W")])


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
    """真三级结构（1 章 → 1.1 节 → 1.1.1 小节）：叶子=三级小节，与生产形态一致。"""
    return Outline(sections=[
        OutlineNode(id="1", title="总体方案", children=[
            OutlineNode(id="1.1", title="设备与部署", children=[
                _leaf("1.1.1", "设备选型", desc="硬件参数"),
                _leaf("1.1.2", "部署架构", desc="网络拓扑")])]),
        OutlineNode(id="2", title="实施方案", children=[
            OutlineNode(id="2.1", title="进度与保障", children=[
                _leaf("2.1.1", "进度安排", desc="里程碑"),
                _leaf("2.1.2", "质保服务", desc="服务体系")])]),
    ], total_words=80)


def _kb_dir(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    kb.mkdir(exist_ok=True)
    (kb / "规格.md").write_text("X100 功率 300W，质保三年。", encoding="utf-8")
    return kb


def _state(tmp_path: Path, **updates) -> BidState:
    return BidState(
        run_id="run-1", kb_dir=str(_kb_dir(tmp_path)),
        facts=GlobalFacts(schedule="90 天"), outline=_outline(), **updates,
    )


def _factory(body_content: str = "正文内容" * 5, need: dict | None = None,
             media: dict | None = None, insert_index: int = 1, captured: list | None = None):
    """按 output_type 分发假输出的工厂：MediaNeed/SectionBody/SectionMedia/InsertPoint。"""

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            prompt = _last_user_content(messages)
            if captured is not None:
                captured.append((output_type.__name__, prompt))
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            if output_type is MediaNeed:
                out = need or {"type": "none", "score": 0.0}
            elif output_type is SectionBody:
                out = {"title": "占位", "content": body_content}
            elif output_type is SectionMedia:
                assert media is not None, "unexpected SectionMedia call"
                out = media
            else:  # InsertPoint
                out = {"index": insert_index}
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=json.dumps(out))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)
    return make


# ---------- E：全局限额（纯函数） ----------

def test_overall_review_keeps_highest_scores_per_type():
    root = Outline(sections=[OutlineNode(id="1", title="章", children=[
        _leaf("1.1", "a"), _leaf("1.2", "b"), _leaf("1.3", "c"), _leaf("1.4", "d")])])
    scores = {"1.1": ("table", 0.9), "1.2": ("table", 0.5),
              "1.3": ("figure", 0.8), "1.4": ("figure", 0.3)}
    for n in root.leaves():
        n.media_type, n.media_score = scores[n.id]
    overall_review_leaves(root, {"table": 1, "figure": 1})
    kept = {n.id: n.media_type for n in root.leaves()}
    assert kept == {"1.1": "table", "1.2": None, "1.3": "figure", "1.4": None}
    by_id = {n.id: n for n in root.leaves()}
    assert by_id["1.2"].media_score == 0.0 and by_id["1.1"].media_score == 0.9


# ---------- G-1：媒体校验与渲染 ----------

@pytest.fixture(autouse=True)
def _no_real_render(monkeypatch):
    """单测默认关掉真实渲染（环境无关、秒回）；live 冒烟测试单独直连 render_check。"""
    monkeypatch.setattr(rb_mod, "render_check", lambda code: None)


def test_validate_media_render_error_becomes_feedback(monkeypatch):
    monkeypatch.setattr(rb_mod, "render_check", lambda code: "Parse error on line 2")
    err = _validate_media(SectionMedia(**VALID_FIGURE))
    assert err and "渲染失败" in err and "Parse error on line 2" in err


def test_validate_media_accepts_and_rejects():
    assert _validate_media(SectionMedia(**VALID_TABLE)) is None
    assert _validate_media(SectionMedia(**VALID_FIGURE)) is None
    # 表格缺分隔行
    bad_table = SectionMedia(type="table", media_content="| a | b |\n| 1 | 2 |", media_caption="t")
    assert _validate_media(bad_table) and "Markdown" in _validate_media(bad_table)
    # mermaid 首词不是图型关键字
    bad_fig = SectionMedia(type="figure", media_content="这是一个流程图：flowchart", media_caption="f")
    assert _validate_media(bad_fig) and "关键字" in _validate_media(bad_fig)
    # 括号不配对
    unbalanced = SectionMedia(type="figure", media_content="flowchart TD\nA[采集 --> B", media_caption="f")
    assert _validate_media(unbalanced) and "不配对" in _validate_media(unbalanced)
    # 缺 caption
    no_cap = SectionMedia(type="table", media_content=VALID_TABLE["media_content"], media_caption="")
    assert _validate_media(no_cap) and "caption" in _validate_media(no_cap)


def test_render_media_strips_fence_and_appends_caption():
    fenced = SectionMedia(type="figure", media_content="```mermaid\nflowchart TD\nA-->B\n```",
                          media_caption="流程")
    out = _render_media(fenced)
    assert out.count("```mermaid") == 1 and out.endswith("流程")   # 双围栏被剥掉
    table_md = _render_media(SectionMedia(**VALID_TABLE))
    assert table_md.startswith("| 型号 |") and table_md.endswith("设备参数")


# ---------- G-2：插入位置 ----------

def test_insert_media_uses_llm_index_and_clamps():
    calls: list = []

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            calls.append(_last_user_content(messages))
            return ModelResponse(parts=[ToolCallPart(
                tool_name=info.output_tools[0].name if info.output_tools else "final_result",
                args=json.dumps({"index": 99}))])   # 越界 -> 收敛到末尾
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    out = insert_media_into_content("段一\n段二\n段三", SectionMedia(**VALID_TABLE), make(InsertPoint, "sys"))
    assert out.splitlines()[0] == "段一" and "| 型号 |" in out and out.rstrip().endswith("设备参数")
    assert "媒体类型】table" in calls[0] and "[2] 段三" in calls[0]


# ---------- D：需求判定 ----------

def test_preset_none_clears_fields():
    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            return ModelResponse(parts=[ToolCallPart(
                tool_name=info.output_tools[0].name if info.output_tools else "final_result",
                args=json.dumps({"type": "none", "score": 0.7}))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    node = _leaf("1.1", "设备选型")
    preset_table_figure(node, make(MediaNeed, "sys"))
    assert node.media_type is None and node.media_score == 0.0


def test_preset_need_sets_clamped_score():
    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            return ModelResponse(parts=[ToolCallPart(
                tool_name=info.output_tools[0].name if info.output_tools else "final_result",
                args=json.dumps({"type": "table", "score": 1.7}))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    node = _leaf("1.1", "设备选型")
    preset_table_figure(node, make(MediaNeed, "sys"))
    assert node.media_type == "table" and node.media_score == 1.0    # 收敛到 0~1


# ---------- body 替换后的回归场景（原 test_node_body 价值用例移植） ----------

def test_rich_body_selective_fix_only_rewrites_problem_leaves(tmp_path: Path, monkeypatch):
    """审核回环：body_fix_sections 只重生成问题小节，反馈进入对应 prompt。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(rb_mod, "make_agent",
                        _factory(need={"type": "none"}, body_content="旧内容" * 5))
    rb_mod.rich_body_node(state)
    d = run_dir(state) / "05_body"
    old_12 = (d / "1.1.2-部署架构.md").read_text(encoding="utf-8")

    fix_state = _state(tmp_path, body_fix_sections=["1.1.1"], body_feedback="[1.1.1] 补充进度计划")
    calls: list = []
    monkeypatch.setattr(rb_mod, "make_agent",
                        _factory(need={"type": "none"}, body_content="修复内容" * 5,
                                 captured=calls))
    rb_mod.rich_body_node(fix_state)

    assert "修复内容" in (d / "1.1.1-设备选型.md").read_text(encoding="utf-8")
    assert (d / "1.1.2-部署架构.md").read_text(encoding="utf-8") == old_12   # 未修复小节不动
    body_prompts = [p_ for k, p_ in calls if k == "SectionBody"]
    assert len(body_prompts) == 1 and "[1.1.1] 补充进度计划" in body_prompts[0]


def test_rich_body_prefers_edited_outline_yaml(tmp_path: Path, monkeypatch):
    """用户编辑 04_outline.yaml 后，正文以文件为准。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    p = run_dir(state) / "04_outline.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "sections:\n- id: '1'\n  title: 用户修改章\n  children:\n"
        "  - id: '1.1'\n    title: 修改要点\n    children:\n"
        "    - id: '1.1.1'\n      title: 修改要点节\n      target_words: 30\n      description: 修改要点\n",
        encoding="utf-8")
    captured: list = []
    monkeypatch.setattr(rb_mod, "make_agent",
                        _factory(need={"type": "none"}, body_content="内容达标" * 5,
                                 captured=captured))
    rb_mod.rich_body_node(state)
    assert any("修改要点" in p_ for _, p_ in captured)          # 编辑后的目录进入 prompt
    assert (run_dir(state) / "05_body" / "1.1.1-修改要点节.md").exists()


def test_body_review_word_violation_marks_fix_id(tmp_path: Path, monkeypatch):
    """联动冒烟：rich_body 产物 -> body_review 字数否决 -> 圈定修复小节。"""
    import json as _json
    from pydantic_ai import Agent as _Agent
    from pydantic_ai.messages import ModelResponse as _MR, ToolCallPart as _TCP
    from pydantic_ai.models.function import AgentInfo as _AI, FunctionModel as _FM

    from biaoshu_gen.config import get_settings
    from biaoshu_gen.nodes import body_review as br_mod

    monkeypatch.chdir(tmp_path)
    # 字数否决语义固定在 ±50%（默认 word_tolerance=1 已放宽为不否决，此处锁行为不随默认漂移）
    monkeypatch.setattr(get_settings(), "word_tolerance", 0.5)
    state = _state(tmp_path)
    # rich：全桩（need=none -> 无媒体调用）；正文 20 字恰好达标
    monkeypatch.setattr(rb_mod, "make_agent",
                        _factory(need={"type": "none"}, body_content="正文内容" * 5))
    body_state = _state(tmp_path, **rb_mod.rich_body_node(state))
    d = run_dir(state) / "05_body"
    (d / "2.1.1-进度安排.md").write_text("太短", encoding="utf-8")   # 远低于字数下限

    # review：独立假模型（LLM 放行，字数否决由代码侧触发）
    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: _AI):
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            out = {"passed": True, "issues": [], "problem_sections": []}
            return _MR(parts=[_TCP(tool_name=tool, args=_json.dumps(out))])
        return _Agent(model=_FM(fn), output_type=output_type,
                      system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(br_mod, "make_agent", make)
    updates = br_mod.body_review_node(body_state)
    assert updates["body_review_passed"] is False                # 代码侧字数否决
    assert "2.1.1" in updates["body_fix_sections"]


def test_rich_body_generates_leaves_concurrently(tmp_path: Path, monkeypatch):
    """三级（叶子）粒度并发：全部叶子在彼此完成前都已开工（屏障超时即败）。"""
    import threading

    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path).model_copy(update={
        "outline": Outline(sections=[
            OutlineNode(id="1", title="总体方案", children=[
                OutlineNode(id="1.1", title="甲节", children=[
                    _leaf("1.1.1", "a1", desc="d"),
                    _leaf("1.1.2", "a2", desc="d")]),
                OutlineNode(id="1.2", title="乙节", children=[
                    _leaf("1.2.1", "b1", desc="d"),
                    _leaf("1.2.2", "b2", desc="d")]),
            ])],
            total_words=80,
        )})

    barrier = threading.Barrier(4, timeout=8)

    def make(output_type, system_prompt, retries=2):
        if output_type is not SectionBody:
            return _factory(need={"type": "none"})(output_type, system_prompt, retries)

        async def fn(messages, info: AgentInfo):
            barrier.wait()                            # 4 叶必须同时开工
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            return ModelResponse(parts=[ToolCallPart(
                tool_name=tool, args=json.dumps({"title": "占位", "content": "正文内容" * 5}))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(rb_mod, "make_agent", make)
    updates = rb_mod.rich_body_node(state)
    assert updates["body_md_path"]


# ---------- 媒体需求判定只做一次（feedback：回环后不再触发） ----------

def test_media_need_not_retriggered_on_review_loop(tmp_path: Path, monkeypatch):
    """首次运行判定并落盘 media_needs.yaml；fix 回环重入时 MediaNeed 零调用。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    captured: list = []
    monkeypatch.setattr(rb_mod, "make_agent",
                        _factory(need={"type": "none"}, captured=captured))
    rb_mod.rich_body_node(state)
    d = run_dir(state) / "05_body"
    assert (d / "media_needs.yaml").exists()
    assert [k for k, _ in captured].count("MediaNeed") == 4        # 首次全判定
    captured.clear()

    fix_state = _state(tmp_path, body_fix_sections=["1.1.1"], body_feedback="补充")
    monkeypatch.setattr(rb_mod, "make_agent",
                        _factory(need={"type": "none"}, body_content="修复内容" * 5,
                                 captured=captured))
    rb_mod.rich_body_node(fix_state)
    assert [k for k, _ in captured].count("MediaNeed") == 0        # 回环零判定
    assert [k for k, _ in captured].count("SectionBody") == 1      # 只重生成问题小节


# ---------- 渲染器 live 冒烟（本机装了 mmdc 才执行） ----------

@pytest.mark.skipif(shutil.which("mmdc") is None, reason="未安装 @mermaid-js/mermaid-cli")
def test_mermaid_render_live():
    assert render_check("flowchart TD\nA[采集] --> B[存储]") is None
    err = render_check("flowchart TD\nA[采集 --> B")
    assert err and ("Parse" in err or "parse" in err)


# ---------- 整节点 ----------

def test_rich_body_full_flow_writes_media_and_body(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    # 所有叶子判定为 table 需求；2.2 分数最低 -> 全局限额 3 个后被清掉
    need = {"type": "table", "score": 0.5}
    captured: list = []
    monkeypatch.setattr(rb_mod, "make_agent",
                        _factory(need=need, media=VALID_TABLE, insert_index=1, captured=captured))
    updates = rb_mod.rich_body_node(state)

    d = run_dir(state) / "05_body"
    assert updates["body_md_path"].endswith("body.md")
    # 3 个小节带表格，1 个被限额清除
    assert (d / "1.1.1-设备选型.media.yaml").exists()
    assert (d / "2.1.2-质保服务.media.yaml").exists() is False
    leaf_md = (d / "1.1.1-设备选型.md").read_text(encoding="utf-8")
    assert "| 型号 | 功率 |" in leaf_md and "设备参数" in leaf_md     # 媒体插入终版已回写
    plain_md = (d / "2.1.2-质保服务.md").read_text(encoding="utf-8")
    assert "| 型号 |" not in plain_md
    body_md = (d / "body.md").read_text(encoding="utf-8")
    assert body_md.count("| 型号 | 功率 |") == 3 and "# 总体方案" in body_md
    # 四类 LLM 调用都发生过：判定(4) + 正文(4) + 媒体(3) + 插入(3)
    kinds = [k for k, _ in captured]
    assert kinds.count("MediaNeed") == 4 and kinds.count("SectionBody") == 4
    assert kinds.count("SectionMedia") == 3 and kinds.count("InsertPoint") == 3
    # 媒体生成 prompt 带上了本节正文（取材依据）
    assert any(k == "SectionMedia" and "正文内容" in p for k, p in captured)


def test_rich_body_degrades_when_media_invalid(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    bad_media = {"type": "table", "media_content": "这不是表格", "media_caption": "t"}
    media_calls: list = []

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            if output_type is SectionMedia:
                media_calls.append(1)                     # 首次 + 反馈重试一次 = 2 次
            out = bad_media if output_type is SectionMedia else \
                ({"type": "table", "score": 0.5} if output_type is MediaNeed
                 else {"index": 1} if output_type is InsertPoint
                 else {"title": "占位", "content": "正文内容" * 5})
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=json.dumps(out))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(rb_mod, "make_agent", make)
    updates = rb_mod.rich_body_node(state)
    assert len(media_calls) == 2 * 3                       # 限额后 3 个小节，每个重试一次
    assert updates["body_md_path"].endswith("body.md")     # 图表全部降级，正文照常产出
    body_md = (run_dir(state) / "05_body" / "body.md").read_text(encoding="utf-8")
    assert "| 型号 |" not in body_md


def test_rich_body_resumes_from_existing_files(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(rb_mod, "make_agent",
                        _factory(need={"type": "figure", "score": 0.9}, media=VALID_FIGURE))
    rb_mod.rich_body_node(state)
    d = run_dir(state) / "05_body"
    first_md = (d / "1.1.1-设备选型.md").read_text(encoding="utf-8")

    calls: list = []
    monkeypatch.setattr(rb_mod, "make_agent",
                        _factory(need={"type": "figure", "score": 0.9},
                                 media=VALID_FIGURE, captured=calls))
    rb_mod.rich_body_node(_state(tmp_path))

    assert (d / "1.1.1-设备选型.md").read_text(encoding="utf-8") == first_md   # 复用未重跑
    assert not any(k == "SectionBody" for k, _ in calls)                     # 正文零调用
    assert not any(k == "SectionMedia" for k, _ in calls)                    # 媒体零调用（yaml 复用）
