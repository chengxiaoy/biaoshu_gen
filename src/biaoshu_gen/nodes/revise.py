"""节点 12：按审核意见修改草稿（harness），版本号管理。

材料（facts/invalidation/scoring/草稿地图）预注入 prompt，消掉 agent 逐文件读的轮次；
指令一次脚本批量改（见 prompts/revise.py）。
"""
from pathlib import Path

from docx import Document

from ..fill_skill import dump_fill_points
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.revise import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def _inject(state: BidState, current_name: str) -> str:
    d = run_dir(state)

    def _read(*rel: str) -> str:
        p = d.joinpath(*rel)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    parts = [
        "【facts.yaml 全文】\n" + _read("03_facts.yaml"),
        "【废标项+扣分项】\n" + _read("01_parse", "invalidation.yaml"),
        "【评分标准】\n" + _read("01_parse", "scoring.yaml"),
    ]
    current = Path(state.draft_docx_path)
    if current.exists():
        parts.append("【草稿可填点地图】\n" + dump_fill_points(Document(str(current))))
    return "\n\n".join(p for p in parts if p)


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
        prompt=(SYSTEM + "\n\n" + build_user_prompt(
            str(out), n, current=Path(state.draft_docx_path).name)
            + "\n\n" + _inject(state, Path(state.draft_docx_path).name)),
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
