"""节点 8：偏离表（harness 填表）。

动态判断依据：**招标文件**中有偏离表要求才执行（feedbacks：招标文件中没有偏离表部分则跳过）；
有响应模板则严格按模板中的偏离表格式填写，无模板则按招标要求新建。
"""
from pathlib import Path

from ..docx_io import template_has_deviation_table
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.deviation_table import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def deviation_table_node(state: BidState) -> dict:
    if not state.tender_path or not template_has_deviation_table(Path(state.tender_path)):
        print("ℹ 招标文件中无偏离表要求，跳过偏离表节点。")
        return {"deviation_docx_path": ""}

    ws = prepare_agent_workspace(state, "06_fill/deviation", [
        (run_dir(state) / "01_parse" / "requirements.yaml", "requirements.yaml"),
        (run_dir(state) / "01_parse" / "scoring.yaml", "scoring.yaml"),
        (run_dir(state) / "03_facts.yaml", "facts.yaml")])
    out = ws / "deviation.docx"
    run_harness_task(HarnessTask(prompt=SYSTEM + "\n\n" + build_user_prompt(str(out)),
                                 cwd=ws, expected_outputs=[out]))
    return {"deviation_docx_path": str(out)}
