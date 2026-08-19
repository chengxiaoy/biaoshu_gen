"""节点 4：技术方案目录生成（人工控制点 2：04_outline.yaml 用户编辑优先）。"""
import re
from pathlib import Path

from ..models import make_agent, run_sync
from ..prompts.outline import SYSTEM, build_user_prompt
from ..schemas import GlobalFacts, Outline, from_yaml_file, to_yaml_file
from ..state import BidState, run_dir

_MIN_SECTIONS = 3        # 章节过少视为生成失败，自动重试
_MAX_GEN_ATTEMPTS = 3
# flash 级模型常把"指令复述/自我纠正"泄漏进 title，命中即剔除该章（常有干净重复项）
_META_LEAK_MARKERS = ("重新输出", "请以最终", "此处命名", "下面重新", "不超过", "请按时完成")
_MAX_TITLE_CHARS = 40


def _sanitize(result: Outline) -> Outline:
    sections = [
        s.model_copy(update={"title": s.title[:_MAX_TITLE_CHARS].strip()})
        for s in result.sections
        if not any(m in s.title for m in _META_LEAK_MARKERS)
    ]
    return result.model_copy(update={"sections": sections})


def _template_context(template_md: str) -> str:
    """模板瘦身：优先取目录树代码块；无代码块时截断，避免压垮小模型。"""
    if not template_md:
        return ""
    m = re.search(r"```[^\n]*\n(.*?)```", template_md, re.S)
    if m:
        return "（响应文件目录树）\n" + m.group(1).strip()
    return template_md[:6000]


def outline_node(state: BidState) -> dict:
    yaml_path = run_dir(state) / "04_outline.yaml"
    if yaml_path.exists():
        return {"outline": from_yaml_file(Outline, yaml_path)}
    template_md = ""
    if state.template_md_path and Path(state.template_md_path).exists():
        template_md = _template_context(
            Path(state.template_md_path).read_text(encoding="utf-8"))
    facts_yaml = run_dir(state) / "03_facts.yaml"
    # 用户编辑优先：03_facts.yaml 存在则以其内容覆盖 state.facts（resume 时不用陈旧值）
    facts = from_yaml_file(GlobalFacts, facts_yaml) if facts_yaml.exists() else state.facts
    agent = make_agent(Outline, SYSTEM)
    prompt = build_user_prompt(
        requirements=state.requirements.model_dump_json(indent=2) if state.requirements else "",
        technical_rules="\n".join(state.scoring.technical_rules) if state.scoring else "",
        facts=facts.model_dump_json(indent=2) if facts else "",
        template_md=template_md,
    )
    result: Outline | None = None
    for _ in range(_MAX_GEN_ATTEMPTS):
        result = _sanitize(run_sync(agent, prompt).output)
        if len(result.sections) >= _MIN_SECTIONS:
            break
    assert result is not None and len(result.sections) >= _MIN_SECTIONS, (
        f"outline 生成质量不合格（清洗后仅 {len(result.sections)} 章），请重试或更换更强模型")
    to_yaml_file(result, yaml_path)
    return {"outline": result}
