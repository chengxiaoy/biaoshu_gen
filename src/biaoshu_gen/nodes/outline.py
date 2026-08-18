"""节点 4：技术方案目录生成（人工控制点 2：04_outline.yaml 用户编辑优先）。"""
from pathlib import Path

from ..models import make_agent
from ..prompts.outline import SYSTEM, build_user_prompt
from ..schemas import Outline, from_yaml_file, to_yaml_file
from ..state import BidState, run_dir


def outline_node(state: BidState) -> dict:
    yaml_path = run_dir(state) / "04_outline.yaml"
    if yaml_path.exists():
        return {"outline": from_yaml_file(Outline, yaml_path)}
    template_md = ""
    if state.template_md_path and Path(state.template_md_path).exists():
        template_md = Path(state.template_md_path).read_text(encoding="utf-8")
    agent = make_agent(Outline, SYSTEM)
    result: Outline = agent.run_sync(build_user_prompt(
        requirements=state.requirements.model_dump_json(indent=2) if state.requirements else "",
        technical_rules="\n".join(state.scoring.technical_rules) if state.scoring else "",
        facts=state.facts.model_dump_json(indent=2) if state.facts else "",
        template_md=template_md,
    )).output
    to_yaml_file(result, yaml_path)
    return {"outline": result}
