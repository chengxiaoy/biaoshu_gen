"""节点 4：技术方案三级目录生成（人工控制点 2：04_outline.yaml 用户编辑优先）。"""
from pathlib import Path

from ..models import make_agent, run_sync
from ..prompts.outline import SYSTEM, build_user_prompt
from ..schemas import GlobalFacts, Outline, OutlineNode, from_yaml_file, to_yaml_file
from ..state import BidState, run_dir

_MIN_SECTIONS = 3        # 一级章过少视为生成失败，自动重试
_MIN_LEAVES = 5          # 三级小节过少同样视为失败
_MAX_GEN_ATTEMPTS = 3
# flash 级模型常把"指令复述/自我纠正"泄漏进 title，命中即剔除该节点（子树一并剔除）
_META_LEAK_MARKERS = ("重新输出", "请以最终", "此处命名", "下面重新", "不超过", "请按时完成")
_MAX_TITLE_CHARS = 40


def _sanitize_node(node: OutlineNode) -> OutlineNode | None:
    if any(m in node.title for m in _META_LEAK_MARKERS):
        return None
    children = [c for c in (_sanitize_node(c) for c in node.children) if c is not None]
    return node.model_copy(update={
        "title": node.title[:_MAX_TITLE_CHARS].strip(),
        "children": children,
    })


def _sanitize(result: Outline) -> Outline:
    sections = [s for s in (_sanitize_node(s) for s in result.sections) if s is not None]
    return result.model_copy(update={"sections": sections})


def outline_node(state: BidState) -> dict:
    yaml_path = run_dir(state) / "04_outline.yaml"
    if yaml_path.exists():
        return {"outline": from_yaml_file(Outline, yaml_path)}
    facts_yaml = run_dir(state) / "03_facts.yaml"
    # 用户编辑优先：03_facts.yaml 存在则以其内容覆盖 state.facts（resume 时不用陈旧值）
    facts = from_yaml_file(GlobalFacts, facts_yaml) if facts_yaml.exists() else state.facts
    agent = make_agent(Outline, SYSTEM)
    prompt = build_user_prompt(
        requirements=state.requirements.model_dump_json(indent=2) if state.requirements else "",
        technical_rules="\n".join(state.scoring.technical_rules) if state.scoring else "",
        facts=facts.model_dump_json(indent=2) if facts else "",
    )
    result: Outline | None = None
    for _ in range(_MAX_GEN_ATTEMPTS):
        result = _sanitize(run_sync(agent, prompt).output)
        if len(result.sections) >= _MIN_SECTIONS and len(result.leaves()) >= _MIN_LEAVES:
            break
    assert result is not None and len(result.sections) >= _MIN_SECTIONS \
        and len(result.leaves()) >= _MIN_LEAVES, (
        f"outline 生成质量不合格（{len(result.sections) if result else 0} 章 / "
        f"{len(result.leaves()) if result else 0} 个三级小节），请重试或更换更强模型")
    # 总字数以叶子之和为准（不信模型自报的 total_words）
    result = result.model_copy(update={"total_words": sum(l.target_words for l in result.leaves())})
    to_yaml_file(result, yaml_path)
    return {"outline": result}
