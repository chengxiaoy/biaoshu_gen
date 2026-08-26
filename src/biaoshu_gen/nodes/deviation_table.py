"""节点 8：偏离表（非 harness）：LLM 直出数据行 + python 整表替换。

表定位/归类与行回写为确定性 python（表头行保留，数据行整换）；
LLM 仅经 PydanticAI 结构化输出两类表的数据行，避开 harness 子进程通道。
跳过 gate 与 deviation_docx_path 契约不变，assemble 侧零改动。
"""
import shutil
from pathlib import Path

from docx import Document

from ..docx_io import find_deviation_tables, replace_table_rows, table_md, template_has_section
from ..fill_context import SECTION_KEYWORDS
from ..models import make_agent, run_sync       # noqa: F401  (测试 monkeypatch dev.make_agent)
from ..prompts.deviation_table import SYSTEM, build_user_prompt
from ..schemas import DeviationTables
from ..state import BidState, run_dir

_RETRY_TIMES = 2   # 首次 + 校验失败重试一次
_MAX_ROWS = 200


class DeviationFillError(RuntimeError):
    """偏离表填写失败（LLM 两次输出均未通过校验）。"""


def _validate(result: DeviationTables) -> DeviationTables:
    rows = result.contract_rows + result.requirement_rows
    if not rows:
        raise ValueError("两个数组同时为空，至少须填写一类表")
    if len(rows) > _MAX_ROWS:
        raise ValueError(f"总行数 {len(rows)} 超过上限 {_MAX_ROWS}")
    for i, r in enumerate(rows):
        if not r.requirement.strip() or not r.response.strip():
            raise ValueError(f"第 {i + 1} 行 requirement/response 为空")
    return result


def _read_text(run: Path, *parts: str) -> str:
    p = run.joinpath(*parts)
    return p.read_text(encoding="utf-8") if p.exists() else f"（{p.name} 缺失）"


def deviation_table_node(state: BidState) -> dict:
    if not state.template_docx_path:
        print("ℹ 无响应模板，跳过 deviation 节点。")
        return {"deviation_docx_path": ""}
    if not template_has_section(Path(state.template_docx_path), SECTION_KEYWORDS["deviation"][0]):
        print(f"ℹ 响应模板中无「{SECTION_KEYWORDS['deviation'][0]}」，跳过 deviation 节点。")
        return {"deviation_docx_path": ""}

    run = run_dir(state)
    ws = run / "06_fill" / "deviation"
    ws.mkdir(parents=True, exist_ok=True)
    out = ws / "deviation.docx"
    shutil.copyfile(state.template_docx_path, out)
    doc = Document(str(out))
    found = find_deviation_tables(doc)
    if not found:
        print("ℹ 响应模板表头中无偏离表，跳过 deviation 节点。")
        return {"deviation_docx_path": ""}

    tables_by_kind: dict[str, object] = {}
    for table, kind in found:
        tables_by_kind.setdefault(kind, table)      # 同类多表取首张
    placeholder = "（无此表，对应数组留空）"

    def _md(kind: str) -> str:
        t = tables_by_kind.get(kind)
        return table_md(t) if t is not None else placeholder

    agent = make_agent(DeviationTables, SYSTEM)
    prompt = build_user_prompt(
        _md("contract"), _md("requirement"),
        _read_text(run, "01_parse", "requirements.yaml"),
        _read_text(run, "01_parse", "invalidation.yaml"),
        _read_text(run, "03_facts.yaml"),
    )
    result: DeviationTables | None = None
    err = ""
    for _ in range(_RETRY_TIMES):
        candidate = run_sync(agent, prompt).output
        try:
            result = _validate(candidate)
            break
        except ValueError as exc:
            err = str(exc)
            prompt = prompt + f"\n\n上一次输出未通过校验（错误：{err}），请修正后重新输出。"
    if result is None:
        raise DeviationFillError(f"偏离表填写失败：两次输出均未通过校验（最后错误：{err}）")

    for kind, table in tables_by_kind.items():
        rows = result.contract_rows if kind == "contract" else result.requirement_rows
        if not rows:
            continue
        data = [[str(i + 1), r.clause, r.requirement, r.response, r.deviation]
                for i, r in enumerate(rows)]
        replace_table_rows(table, data)
    doc.save(str(out))
    return {"deviation_docx_path": str(out)}
