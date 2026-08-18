"""节点 2：投标模板抽取（harness：Claude Code SDK）。"""
from pathlib import Path

from ..harness import HarnessTask, prepare_workspace, run_harness_task
from ..prompts.extract_template import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def extract_template_node(state: BidState) -> dict:
    d = run_dir(state)
    inputs = [(d / "01_parse" / "tender.md", "tender.md")]
    if state.template_docx_path:
        inputs.append((Path(state.template_docx_path), "标书模板.docx"))
    ws = prepare_workspace(d, "02_template", inputs)
    template_md = ws / "template.md"
    report_md = ws / "report.md"
    run_harness_task(HarnessTask(
        prompt=SYSTEM + "\n\n" + build_user_prompt(bool(state.template_docx_path)),
        cwd=ws,
        expected_outputs=[template_md, report_md],
    ))
    return {"template_md_path": str(template_md), "template_report_path": str(report_md)}
