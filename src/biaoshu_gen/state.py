"""LangGraph 全局状态：节点返回 dict 部分更新本模型字段。"""
from pathlib import Path

from pydantic import BaseModel

from .config import get_settings
from .schemas import (
    GlobalFacts, InvalidationItems, Outline, ScoringStandards,
    TenderMetadata, TenderRequirements,
)


class BidState(BaseModel):
    run_id: str = ""
    tender_path: str = ""
    kb_dir: str = ""
    template_docx_path: str = ""      # 招标文件同目录下发现的 *模板*.docx（可为空）

    # 01_parse
    metadata: TenderMetadata | None = None
    requirements: TenderRequirements | None = None
    scoring: ScoringStandards | None = None
    invalidation: InvalidationItems | None = None

    # 02_template
    template_md_path: str = ""
    template_report_path: str = ""

    # 03/04
    facts: GlobalFacts | None = None
    outline: Outline | None = None

    # 05_body
    body_md_path: str = ""
    body_feedback: str = ""           # body_review 给 body 的回环意见
    body_review_rounds: int = 0
    body_review_passed: bool = False

    # 06_fill
    forms_docx_path: str = ""
    deviation_docx_path: str = ""
    commercial_docx_path: str = ""

    # 07_draft
    draft_docx_path: str = ""
    draft_md_path: str = ""
    draft_version: int = 0

    # 08_review
    review_report_path: str = ""
    review_passed: bool = False
    revision_round: int = 0

    errors: list[str] = []


def run_dir(state: BidState) -> Path:
    return get_settings().data_dir / "runs" / state.run_id
