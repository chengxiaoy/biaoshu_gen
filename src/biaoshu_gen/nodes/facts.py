"""节点 3：全局事实设定（人工控制点 1：03_facts.yaml 用户编辑优先）。

facts 阶段读取响应模板（extract_template 产出的 标书模板.docx）的表格部分，
提炼填表所需信息（项目名称/编号/备案号等）预置到 template_fields。
"""
from pathlib import Path

from ..docx_io import docx_to_markdown
from ..models import make_agent, run_sync
from ..prompts.facts import SYSTEM, build_user_prompt
from ..schemas import GlobalFacts, to_yaml_file
from ..state import BidState, run_dir


def facts_node(state: BidState) -> dict:
    yaml_path = run_dir(state) / "03_facts.yaml"
    if yaml_path.exists():                       # 用户已编辑（或上游已产出）-> 不调 LLM
        from ..fill_context import load_facts
        return {"facts": load_facts(state)}
    template_md = ""
    if state.template_docx_path and Path(state.template_docx_path).exists():
        template_md = docx_to_markdown(Path(state.template_docx_path))
    agent = make_agent(GlobalFacts, SYSTEM)
    result: GlobalFacts = run_sync(agent, build_user_prompt(
        metadata=state.metadata.model_dump_json(indent=2) if state.metadata else "",
        scoring=state.scoring.model_dump_json(indent=2) if state.scoring else "",
        template_md=template_md,
    )).output
    to_yaml_file(result, yaml_path)
    return {"facts": result}
