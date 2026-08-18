"""节点 12：按审核意见修改草稿（harness），版本号管理。"""
from pathlib import Path

from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.revise import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def revise_node(state: BidState) -> dict:
    d = run_dir(state)
    n = state.draft_version + 1
    ws = prepare_agent_workspace(state, "07_draft", [
        (Path(state.draft_docx_path), Path(state.draft_docx_path).name),
        (Path(state.review_report_path), "review_report.md"),
        (d / "03_facts.yaml", "facts.yaml"),
    ])
    out = ws / f"标书草稿_v{n}.docx"
    run_harness_task(HarnessTask(
        prompt=SYSTEM + "\n\n" + build_user_prompt(
            str(out), n, current=Path(state.draft_docx_path).name),
        cwd=ws, expected_outputs=[out]))
    (ws / "latest.txt").write_text(str(n), encoding="utf-8")
    updates: dict = {
        "draft_docx_path": str(out),
        "draft_version": n,
        "revision_round": state.revision_round + 1,
    }
    md_out = ws / f"标书草稿_v{n}.md"
    if md_out.exists():
        updates["draft_md_path"] = str(md_out)
    return updates
