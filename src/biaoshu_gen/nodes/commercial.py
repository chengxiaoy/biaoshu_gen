"""节点 9：商务响应文件（harness 按响应模板格式填写）。

在响应模板副本的"商务部分"中插入信息文字/图片，而非生成后插入；
模板中无商务部分则跳过。模板地图等**预注入 prompt**，压缩轮次。
"""
from pathlib import Path

from ..docx_io import template_has_section
from ..fill_context import build_fill_context, prefill_known
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.commercial import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def commercial_node(state: BidState) -> dict:
    if not state.template_docx_path:
        print("ℹ 无响应模板，跳过商务响应节点。")
        return {"commercial_docx_path": ""}
    if not template_has_section(Path(state.template_docx_path), "商务"):
        print("ℹ 响应模板中无商务部分，跳过商务响应节点。")
        return {"commercial_docx_path": ""}

    ws = prepare_agent_workspace(state, "06_fill/commercial", [
        (run_dir(state) / "01_parse" / "scoring.yaml", "scoring.yaml"),
        (run_dir(state) / "01_parse" / "metadata.yaml", "metadata.yaml"),
        (run_dir(state) / "03_facts.yaml", "facts.yaml")])
    out = ws / "commercial.docx"
    prefilled = prefill_known(ws / "标书模板.docx", state)   # 确定值代码直填
    prompt = (SYSTEM + "\n\n" + build_user_prompt(str(out))
              + "\n\n" + build_fill_context(state, template_path=ws / "标书模板.docx"))
    if prefilled:
        prompt += "\n\n【系统已预填字段（勿在 PLAN 中重复填写；发现遗漏才补）】\n- " + "\n- ".join(prefilled)
    run_harness_task(HarnessTask(prompt=prompt, cwd=ws, expected_outputs=[out]))
    return {"commercial_docx_path": str(out)}
