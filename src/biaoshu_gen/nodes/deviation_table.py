"""节点 8：偏离表（harness 填表）。"""
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.deviation_table import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def deviation_table_node(state: BidState) -> dict:
    ws = prepare_agent_workspace(state, "06_fill/deviation", [
        (run_dir(state) / "01_parse" / "requirements.yaml", "requirements.yaml"),
        (run_dir(state) / "01_parse" / "scoring.yaml", "scoring.yaml"),
        (run_dir(state) / "03_facts.yaml", "facts.yaml")])
    out = ws / "deviation.docx"
    run_harness_task(HarnessTask(prompt=SYSTEM + "\n\n" + build_user_prompt(str(out)),
                                 cwd=ws, expected_outputs=[out]))
    return {"deviation_docx_path": str(out)}
