"""节点 9：商务响应文件（harness 填表）。"""
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.commercial import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def commercial_node(state: BidState) -> dict:
    ws = prepare_agent_workspace(state, "06_fill/commercial", [
        (run_dir(state) / "01_parse" / "scoring.yaml", "scoring.yaml"),
        (run_dir(state) / "01_parse" / "metadata.yaml", "metadata.yaml"),
        (run_dir(state) / "03_facts.yaml", "facts.yaml")])
    out = ws / "commercial.docx"
    run_harness_task(HarnessTask(prompt=SYSTEM + "\n\n" + build_user_prompt(str(out)),
                                 cwd=ws, expected_outputs=[out]))
    return {"commercial_docx_path": str(out)}
