"""节点 6：正文审核检验（一致性/事实/废标扣分/字数 ±20%）。"""
from pathlib import Path

from ..config import get_settings
from ..kb import count_chars
from ..models import make_agent
from ..prompts.body_review import SYSTEM, build_user_prompt
from ..schemas import BodyReviewReport, Outline, from_yaml_file
from ..state import BidState, run_dir


def _outline_for_use(state: BidState) -> Outline:
    """用户编辑优先：04_outline.yaml 存在则覆盖 state.outline（resume 时不用陈旧值）。"""
    yaml_path = run_dir(state) / "04_outline.yaml"
    if yaml_path.exists():
        return from_yaml_file(Outline, yaml_path)
    assert state.outline, "outline 未生成，无法撰写正文"
    return state.outline


def body_review_node(state: BidState) -> dict:
    assert state.body_md_path, "body 未生成"
    outline = _outline_for_use(state)
    d = run_dir(state) / "05_body"
    tolerance = get_settings().word_tolerance

    rows: list[str] = []
    word_issues: list[str] = []
    for i, sec in enumerate(outline.sections, 1):
        matches = sorted(d.glob(f"{i:02d}-*.md"))
        assert matches, f"章节文件缺失: {d}/{i:02d}-*.md"
        actual = count_chars(matches[0].read_text(encoding="utf-8"))
        rows.append(f"- 《{sec.title}》 目标 {sec.target_words} 字 / 实际 {actual} 字")
        if actual < sec.target_words * (1 - tolerance):
            word_issues.append(f"章节《{sec.title}》字数不足：目标约 {sec.target_words}，实际 {actual}")
        elif actual > sec.target_words * (1 + tolerance):
            word_issues.append(f"章节《{sec.title}》字数超出：目标约 {sec.target_words}，实际 {actual}")

    invalidation_text = ""
    if state.invalidation:
        invalidation_text = "\n".join(
            f"[{it.kind}] {it.requirement}（依据：{it.source_quote}）"
            for it in state.invalidation.items)

    body = Path(state.body_md_path).read_text(encoding="utf-8")
    agent = make_agent(BodyReviewReport, SYSTEM)
    report: BodyReviewReport = agent.run_sync(build_user_prompt(
        facts=state.facts.model_dump_json(indent=2) if state.facts else "",
        invalidation=invalidation_text,
        word_table="\n".join(rows),
        body=body,
    )).output

    issues = list(report.issues) + word_issues
    passed = report.passed and not word_issues
    rounds = state.body_review_rounds + 1
    report_path = d / f"body_review_round_{rounds}.md"
    report_path.write_text(
        f"# 正文审核 第 {rounds} 轮\n\n结论：{'通过' if passed else '不通过'}\n\n"
        "## 问题清单\n" + ("\n".join(f"- {i}" for i in issues) or "- 无"),
        encoding="utf-8",
    )
    return {
        "body_review_passed": passed,
        "body_feedback": "；".join(issues),
        "body_review_rounds": rounds,
    }
