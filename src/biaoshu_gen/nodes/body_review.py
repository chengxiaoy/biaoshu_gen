"""节点 6：正文审核检验（叶子小节粒度：字数 ±20% + 一致性），圈定需修复的小节 id。"""
from pathlib import Path

from ..config import get_settings
from ..kb import count_chars
from ..models import make_agent, run_sync
from ..prompts.body_review import SYSTEM, build_user_prompt
from ..schemas import BodyReviewReport, from_yaml_file
from ..state import BidState, run_dir

from .body import _leaf_file, _outline_for_use


def body_review_node(state: BidState) -> dict:
    assert state.body_md_path, "body 未生成"
    outline = _outline_for_use(state)
    d = run_dir(state) / "05_body"
    tolerance = get_settings().word_tolerance

    rows: list[str] = []
    word_issues: list[str] = []
    word_fix_ids: list[str] = []
    for leaf in outline.leaves():
        f = _leaf_file(d, leaf)
        assert f.exists(), f"小节文件缺失: {f}"
        actual = count_chars(f.read_text(encoding="utf-8"))
        rows.append(f"- [{leaf.id}] {leaf.title}：目标 {leaf.target_words} 字 / 实际 {actual} 字")
        if actual < leaf.target_words * (1 - tolerance):
            word_issues.append(f"[{leaf.id}]《{leaf.title}》字数不足：目标约 {leaf.target_words}，实际 {actual}")
            word_fix_ids.append(leaf.id)
        elif actual > leaf.target_words * (1 + tolerance):
            word_issues.append(f"[{leaf.id}]《{leaf.title}》字数超出：目标约 {leaf.target_words}，实际 {actual}")
            word_fix_ids.append(leaf.id)

    invalidation_text = ""
    if state.invalidation:
        invalidation_text = "\n".join(
            f"[{it.kind}] {it.requirement}（依据：{it.source_quote}）"
            for it in state.invalidation.items)

    body = Path(state.body_md_path).read_text(encoding="utf-8")
    agent = make_agent(BodyReviewReport, SYSTEM)
    report: BodyReviewReport = run_sync(agent, build_user_prompt(
        facts=state.facts.model_dump_json(indent=2) if state.facts else "",
        invalidation=invalidation_text,
        word_table="\n".join(rows),
        body=body,
    )).output

    leaf_ids = {l.id for l in outline.leaves()}
    fix_ids = sorted({i for i in report.problem_sections if i in leaf_ids} | set(word_fix_ids))
    issues = list(report.issues) + word_issues
    passed = report.passed and not word_issues and not fix_ids
    rounds = state.body_review_rounds + 1
    report_path = d / f"body_review_round_{rounds}.md"
    report_path.write_text(
        f"# 正文审核 第 {rounds} 轮\n\n结论：{'通过' if passed else '不通过'}\n\n"
        "## 问题清单\n" + ("\n".join(f"- {i}" for i in issues) or "- 无") +
        "\n\n## 待修复小节\n" + ("\n".join(f"- {i}" for i in fix_ids) or "- 无"),
        encoding="utf-8",
    )
    return {
        "body_review_passed": passed,
        "body_feedback": "；".join(issues),
        "body_fix_sections": fix_ids,
        "body_review_rounds": rounds,
    }
