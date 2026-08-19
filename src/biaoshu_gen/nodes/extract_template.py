"""节点 2：投标模板抽取（harness）：从招标文件中提取响应文件模板。

产出 template.md（目录树+填写要求）、report.md（用户报告）与 标书模板.docx
（从招标文件"投标文件的格式"章节提取的可填写模板副本）；
后续 fill 节点与 assemble 均以该模板副本为格式底稿。
"""
from pathlib import Path

from ..harness import HarnessTask, prepare_workspace, run_harness_task
from ..prompts.extract_template import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def extract_template_node(state: BidState) -> dict:
    d = run_dir(state)
    inputs = [
        (d / "01_parse" / "tender.md", "tender.md"),
        (Path(state.tender_path), "招标文件.docx"),      # 模板从招标文件原文提取
    ]
    if state.template_docx_path:                          # init 发现的随附模板（若有，作参考）
        inputs.append((Path(state.template_docx_path), "投标模板参考.docx"))
    ws = prepare_workspace(d, "02_template", inputs)
    template_md = ws / "template.md"
    report_md = ws / "report.md"
    tpl_docx = ws / "标书模板.docx"
    run_harness_task(HarnessTask(
        prompt=SYSTEM + "\n\n" + build_user_prompt(bool(state.template_docx_path)),
        cwd=ws,
        expected_outputs=[template_md, report_md, tpl_docx],
    ))
    return {
        "template_md_path": str(template_md),
        "template_report_path": str(report_md),
        "template_docx_path": str(tpl_docx),
    }
