"""节点 11：Agent 全面审核（harness），VERDICT 结论解析。"""
from pathlib import Path

from ..config import get_settings
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.review import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def _parse_verdict(report: Path) -> str:
    for line in reversed(report.read_text(encoding="utf-8").splitlines()):
        stripped = line.strip().upper()
        if stripped.startswith("VERDICT:"):
            return "PASS" if "PASS" in stripped else "FAIL"
    return "FAIL"                                   # 未找到结论 → 保守判 FAIL


def review_node(state: BidState) -> dict:
    d = run_dir(state)
    ws = prepare_agent_workspace(state, "08_review", [
        (Path(state.draft_docx_path), "标书草稿.docx"),
        (Path(state.draft_md_path), "标书草稿.md"),
        (d / "01_parse" / "scoring.yaml", "scoring.yaml"),
        (d / "03_facts.yaml", "facts.yaml"),
    ])
    n = state.revision_round + 1
    out = ws / f"review_round_{n}.md"
    run_harness_task(HarnessTask(prompt=SYSTEM + "\n\n" + build_user_prompt(str(out)),
                                 cwd=ws, expected_outputs=[out]))
    verdict = _parse_verdict(out)
    if verdict == "FAIL" and state.revision_round >= get_settings().revise_max_rounds:
        with out.open("a", encoding="utf-8") as f:      # 路由将到 END → 人工接管
            f.write("\n\n## 需人工处理\n\n已达到修改轮次上限，遗留问题需人工处理（人工审核签字环节）。\n")
    return {"review_passed": verdict == "PASS", "review_report_path": str(out)}
