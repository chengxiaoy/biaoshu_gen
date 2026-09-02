"""LangGraph 全局状态：节点返回 dict 部分更新本模型字段。"""
import operator
from pathlib import Path
from typing import Annotated

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

    # 03/04
    facts: GlobalFacts | None = None
    outline: Outline | None = None

    # 05_body
    body_md_path: str = ""
    body_feedback: str = ""           # body_review 给 body 的回环意见
    body_fix_sections: list[str] = [] # 需修复的三级小节 id（回环时只重生成这些小节）
    body_review_rounds: int = 0
    body_review_passed: bool = False

    # 06_fill
    forms_docx_path: str = ""
    deviation_docx_path: str = ""
    commercial_docx_path: str = ""
    template_parts: dict[str, str] = {}    # 模板四分拆:bucket -> part docx 路径(各桶首段)
    # 同桶多区间时附加段的填充产物 run_key -> docx 路径。
    # Annotated reducer:三个 fill 节点在并行 superstep 各写己键,or 合并不互相覆盖
    extra_products: Annotated[dict[str, str], operator.or_] = {}

    # 07_draft
    draft_docx_path: str = ""
    draft_md_path: str = ""
    draft_version: int = 0

    # 08_review
    review_report_path: str = ""
    review_passed: bool = False
    revision_round: int = 0


def run_dir(state: BidState) -> Path:
    return get_settings().data_dir / "runs" / state.run_id


def write_node_error(state: BidState, name: str, text: str) -> Path:
    """节点错误落盘 06_fill/<name>.error.log(软失败/部分保留共用的统一出口)。"""
    d = run_dir(state) / "06_fill"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.error.log"
    p.write_text(text, encoding="utf-8")
    return p
