"""节点 12：按审核意见修改草稿（harness），版本号管理。

只预注入**小体积**材料（facts/invalidation/scoring，~K token 级）；
**不注入草稿地图**（成品 docx 地图 600+ 行/13K token，且 agent 自己 dump 一次会重复两份，
拖慢每一轮 LLM 调用——实测注入后每轮从 17s 涨到 37s）。
指令一次脚本批量改（见 prompts/revise.py）。
"""
from pathlib import Path

from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.revise import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def _inject(state: BidState) -> str:
    d = run_dir(state)

    def _read(*rel: str) -> str:
        p = d.joinpath(*rel)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    parts = [
        "【facts.yaml 全文】\n" + _read("03_facts.yaml"),
        "【废标项+扣分项】\n" + _read("01_parse", "invalidation.yaml"),
        "【评分标准】\n" + _read("01_parse", "scoring.yaml"),
    ]
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
            + "\n\n" + _inject(state)),
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
