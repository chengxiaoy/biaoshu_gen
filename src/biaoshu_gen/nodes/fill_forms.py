"""节点 7：投标函+报价文件+货物一览表+资格证明文件（harness 填表）。"""
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.fill_forms import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def fill_forms_node(state: BidState) -> dict:
    ws = prepare_agent_workspace(state, "06_fill/forms", [
        (run_dir(state) / "01_parse" / "metadata.yaml", "metadata.yaml")])
    out = ws / "forms.docx"
    run_harness_task(HarnessTask(prompt=SYSTEM + "\n\n" + build_user_prompt(str(out)),
                                 cwd=ws, expected_outputs=[out]))
    return {"forms_docx_path": str(out)}
