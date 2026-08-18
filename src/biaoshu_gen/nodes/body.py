"""节点 5：逐章生成技术方案正文。"""
import re
from pathlib import Path

from ..kb import KnowledgeBase
from ..models import make_agent
from ..prompts.body import SYSTEM, build_user_prompt
from ..schemas import SectionBody
from ..state import BidState, run_dir


def _safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "-", title).strip("-")[:40] or "section"


def body_node(state: BidState) -> dict:
    assert state.outline, "outline 未生成，无法撰写正文"
    d = run_dir(state) / "05_body"
    d.mkdir(parents=True, exist_ok=True)
    kb = KnowledgeBase.load(Path(state.kb_dir))
    facts_text = state.facts.model_dump_json(indent=2) if state.facts else ""
    agent = make_agent(SectionBody, SYSTEM)
    parts: list[str] = []
    for i, sec in enumerate(state.outline.sections, 1):
        snippets = kb.search(sec.title + " " + " ".join(sec.key_points))
        kb_text = "\n\n".join(f"【{c.source.name}】\n{c.text}" for c in snippets) or "（无）"
        result: SectionBody = agent.run_sync(build_user_prompt(
            title=sec.title, target_words=sec.target_words, key_points=sec.key_points,
            facts=facts_text, kb=kb_text, feedback=state.body_feedback,
        )).output
        (d / f"{i:02d}-{_safe_name(sec.title)}.md").write_text(result.content, encoding="utf-8")
        parts.append(f"# {result.title}\n\n{result.content}")
    body_md = d / "body.md"
    body_md.write_text("\n\n".join(parts), encoding="utf-8")
    return {"body_md_path": str(body_md), "body_feedback": ""}
