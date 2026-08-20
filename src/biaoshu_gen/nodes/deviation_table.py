"""节点 8：偏离表（harness 填表）。

动态判断依据：**响应模板（标书模板.docx）中有偏离表模板才执行**；
响应模板中无偏离表模板则跳过节点（deviation_docx_path 置空，assemble 会忽略）。
"""
from pathlib import Path

from ..docx_io import template_has_deviation_table
from ..fill_context import build_fill_context, prefill_known
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.deviation_table import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def deviation_table_node(state: BidState) -> dict:
    if not state.template_docx_path \
            or not template_has_deviation_table(Path(state.template_docx_path)):
        print("ℹ 响应模板中无偏离表模板，跳过偏离表节点。")
        return {"deviation_docx_path": ""}

    ws = prepare_agent_workspace(state, "06_fill/deviation", [
        (run_dir(state) / "01_parse" / "requirements.yaml", "requirements.yaml"),
        (run_dir(state) / "01_parse" / "scoring.yaml", "scoring.yaml"),
        (run_dir(state) / "03_facts.yaml", "facts.yaml")])
    out = ws / "deviation.docx"
    prefilled = prefill_known(ws / "标书模板.docx", state)   # 确定值代码直填
    prompt = (SYSTEM + "\n\n" + build_user_prompt(str(out))
              + "\n\n" + build_fill_context(state, template_path=ws / "标书模板.docx"))
    if prefilled:
        prompt += "\n\n【系统已预填字段（勿在 PLAN 中重复填写；发现遗漏才补）】\n- " + "\n- ".join(prefilled)
    run_harness_task(HarnessTask(prompt=prompt, cwd=ws, expected_outputs=[out]))
    return {"deviation_docx_path": str(out)}
