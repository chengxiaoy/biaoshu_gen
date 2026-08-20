"""节点 11：标书草稿全面审核（PydanticAI 单次调用，非 harness）。

节点代码把草稿全文 + facts + invalidation + scoring + 模板结构预注入 prompt，
单次 LLM 调用得结构化 ReviewReport；避免 harness 逐文件探查与 shell 快照开销。
"""
from pathlib import Path

from ..config import get_settings
from ..docx_io import docx_to_markdown
from ..models import make_agent, run_sync
from ..prompts.review import SYSTEM, build_user_prompt
from ..schemas import ReviewReport
from ..state import BidState, run_dir


def review_node(state: BidState) -> dict:
    d = run_dir(state)
    n = state.revision_round + 1
    out = d / "08_review" / f"review_round_{n}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    def _read(*rel: str) -> str:
        p = d.joinpath(*rel)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    template_md = _read("02_template", "template.md")
    draft_md = docx_to_markdown(Path(state.draft_docx_path))
    agent = make_agent(ReviewReport, SYSTEM)
    report: ReviewReport = run_sync(agent, build_user_prompt(
        draft=draft_md,
        facts=_read("03_facts.yaml"),
        invalidation=_read("01_parse", "invalidation.yaml"),
        scoring=_read("01_parse", "scoring.yaml"),
        template=template_md,
    )).output

    aspect_lines = "\n".join(
        f"- [{a.name}] {'通过' if a.passed else '不通过'}：{a.note}" for a in report.aspects)
    out.write_text(
        f"# 标书草稿审核报告（Round {n}）\n\n## 总体结论\n\n"
        f"{'通过' if report.passed else '不通过'}\n\n"
        "## 分项审核\n" + (aspect_lines or "- 无") +
        "\n\n## 问题清单\n" + ("\n".join(f"- {i}" for i in report.issues) or "- 无") +
        "\n\nVERDICT: " + ("PASS" if report.passed else "FAIL") + "\n",
        encoding="utf-8",
    )
    if not report.passed and state.revision_round >= get_settings().revise_max_rounds:
        with out.open("a", encoding="utf-8") as f:      # 路由将到 END → 人工接管
            f.write("\n## 需人工处理\n\n已达到修改轮次上限，遗留问题需人工处理（人工审核签字环节）。\n")
    return {"review_passed": report.passed, "review_report_path": str(out)}
