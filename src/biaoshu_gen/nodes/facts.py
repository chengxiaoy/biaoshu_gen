"""节点 3：全局事实设定（人工控制点 1：03_facts.yaml 用户编辑优先）。"""
from ..models import make_agent
from ..prompts.facts import SYSTEM, build_user_prompt
from ..schemas import GlobalFacts, from_yaml_file, to_yaml_file
from ..state import BidState, run_dir


def facts_node(state: BidState) -> dict:
    yaml_path = run_dir(state) / "03_facts.yaml"
    if yaml_path.exists():                       # 用户已编辑（或上游已产出）-> 不调 LLM
        return {"facts": from_yaml_file(GlobalFacts, yaml_path)}
    agent = make_agent(GlobalFacts, SYSTEM)
    result: GlobalFacts = agent.run_sync(build_user_prompt(
        metadata=state.metadata.model_dump_json(indent=2) if state.metadata else "",
        scoring=state.scoring.model_dump_json(indent=2) if state.scoring else "",
    )).output
    to_yaml_file(result, yaml_path)
    return {"facts": result}
