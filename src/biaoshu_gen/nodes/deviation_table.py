"""节点 8：偏离表（非 harness）：LLM 按发现的表动态直出数据行 + python 整表替换。

表定位（表头含「偏离」）与表标题提取为确定性 python，支持合同条款/技术/商务/
采购需求等任意偏离表形态；prompt 按发现的表动态构造（序号标注），LLM 结构化
输出按表序号回写（表头行保留，数据行整换），避开 harness 子进程通道。
跳过 gate 与 deviation_docx_path 契约不变，assemble 侧零改动。
"""
import shutil
from pathlib import Path

from docx import Document

from ..docx_io import find_deviation_tables, replace_table_rows, table_md, template_has_section
from ..fill_context import SECTION_KEYWORDS, resolve_template_src
from ..models import make_agent, run_sync       # noqa: F401  (测试 monkeypatch dev.make_agent)
from ..prompts.deviation_table import SYSTEM, build_table_section, build_user_prompt
from ..schemas import DeviationTables
from ..state import BidState, run_dir

_RETRY_TIMES = 2   # 首次 + 校验失败重试一次
_MAX_ROWS = 200


class DeviationFillError(RuntimeError):
    """偏离表填写失败（LLM 两次输出均未通过校验）。"""


def _validate(result: DeviationTables, n_tables: int) -> DeviationTables:
    if not result.tables:
        raise ValueError("tables 为空，至少须填写一张表")
    seen: set[int] = set()
    total = 0
    for t in result.tables:
        if not 1 <= t.table_index <= n_tables:
            raise ValueError(f"table_index {t.table_index} 超出发现的表数（1~{n_tables}）")
        if t.table_index in seen:
            raise ValueError(f"table_index {t.table_index} 重复")
        seen.add(t.table_index)
        total += len(t.rows)
        for i, r in enumerate(t.rows):
            if not r.requirement.strip() or not r.response.strip():
                raise ValueError(f"表{t.table_index} 第 {i + 1} 行 requirement/response 为空")
    if total == 0:
        raise ValueError("所有表的 rows 均为空，至少一张表须有数据行")
    if total > _MAX_ROWS:
        raise ValueError(f"总行数 {total} 超过上限 {_MAX_ROWS}")
    return result


def _read_text(run: Path, *parts: str) -> str:
    p = run.joinpath(*parts)
    return p.read_text(encoding="utf-8") if p.exists() else f"（{p.name} 缺失）"


def deviation_table_node(state: BidState) -> dict:
    tpl_src = resolve_template_src(state, "deviation")
    if not tpl_src:
        print("ℹ 无响应模板，跳过 deviation 节点。")
        return {"deviation_docx_path": ""}
    using_part = tpl_src != (state.template_docx_path or "")
    if not using_part and not template_has_section(Path(tpl_src), SECTION_KEYWORDS["deviation"][0]):
        print(f"ℹ 响应模板中无「{SECTION_KEYWORDS['deviation'][0]}」，跳过 deviation 节点。")
        return {"deviation_docx_path": ""}

    run = run_dir(state)
    ws = run / "06_fill" / "deviation"
    ws.mkdir(parents=True, exist_ok=True)
    out = ws / "deviation.docx"
    shutil.copyfile(tpl_src, out)
    doc = Document(str(out))
    found = find_deviation_tables(doc)
    if not found:
        print("ℹ 响应模板表头中无偏离表，跳过 deviation 节点。")
        return {"deviation_docx_path": ""}

    sections = [build_table_section(i, caption, table_md(t))
                for i, (t, caption) in enumerate(found, start=1)]
    prompt = build_user_prompt(
        sections,
        _read_text(run, "01_parse", "requirements.yaml"),
        _read_text(run, "01_parse", "invalidation.yaml"),
        _read_text(run, "03_facts.yaml"),
    )
    agent = make_agent(DeviationTables, SYSTEM)
    result: DeviationTables | None = None
    err = ""
    for _ in range(_RETRY_TIMES):
        candidate = run_sync(agent, prompt).output
        try:
            result = _validate(candidate, len(found))
            break
        except ValueError as exc:
            err = str(exc)
            prompt = prompt + f"\n\n上一次输出未通过校验（错误：{err}），请修正后重新输出。"
    if result is None:
        raise DeviationFillError(f"偏离表填写失败：两次输出均未通过校验（最后错误：{err}）")

    rows_by_index = {t.table_index: t.rows for t in result.tables}
    for i, (table, _caption) in enumerate(found, start=1):
        rows = rows_by_index.get(i, [])
        if not rows:
            continue
        data = [[str(j + 1), r.clause, r.requirement, r.response, r.deviation]
                for j, r in enumerate(rows)]
        replace_table_rows(table, data)
    doc.save(str(out))
    return {"deviation_docx_path": str(out)}
