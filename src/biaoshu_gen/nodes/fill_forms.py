"""节点 7：投标函+报价文件+货物一览表+资格证明文件（非 harness）。

LLM 直出填写 plan（FillOp 列表），python 经 fill_skill.run_fill_plan 执行；
执行报错回炉修正（≤2 轮）。确定值（项目名称等）仍由代码预填。
skip gate 与 forms_docx_path 契约不变。
"""
import shutil
from pathlib import Path

from docx import Document

from ..business import ensure_business_fields
from ..fill_context import (
    PREFILL_NOTE, VALUE_PRIORITY, build_fill_context, prefill_known,
    resolve_template_src,
)
from ..fill_skill import run_fill_plan
from ..models import make_agent, run_sync       # noqa: F401  (测试 monkeypatch ff.make_agent)
from ..prompts.fill_forms import SYSTEM, build_user_prompt
from ..schemas import FormsFill
from ..state import BidState, run_dir

_OP_KINDS = {"blank", "replace", "cell", "picture", "append"}
_PLAN_RETRY = 2      # plan 校验失败重试一次
_FIX_ROUNDS = 2      # 执行报错修正轮次上限


class FormsFillError(RuntimeError):
    """forms 填写失败（plan 校验不过或报错修正轮次耗尽）。"""


def _validate(result: FormsFill) -> FormsFill:
    if not result.plan:
        raise ValueError("plan 为空")
    for i, op in enumerate(result.plan):
        if op.op not in _OP_KINDS:
            raise ValueError(f"第 {i + 1} 条 op 未知: {op.op}")
    return result


def _ops_of(result: FormsFill) -> list[dict]:
    return [op.model_dump(exclude_none=True) for op in result.plan]


def fill_forms_node(state: BidState) -> dict:
    facts = ensure_business_fields(state)       # 企业/法人/信用代码缺失则 mock 并回写 facts.yaml
    tpl_src = resolve_template_src(state, "forms")
    if not tpl_src:
        print("ℹ 无响应模板，跳过 fill_forms 节点。")
        return {"forms_docx_path": ""}

    run = run_dir(state)
    ws = run / "06_fill" / "forms"
    ws.mkdir(parents=True, exist_ok=True)
    out = ws / "forms.docx"
    shutil.copyfile(tpl_src, out)

    doc = Document(str(out))                    # 只解析一次：预填 + 地图共用
    prefilled = prefill_known(doc, state)
    doc.save(str(out))

    prompt = (SYSTEM + "\n\n"
              + build_user_prompt(str(out), facts.company_name, facts.legal_person,
                                  facts.credit_code)
              + "\n\n" + build_fill_context(state, tpl_doc=doc)
              + "\n\n" + VALUE_PRIORITY)
    if prefilled:
        prompt += "\n\n" + PREFILL_NOTE + "\n- ".join(prefilled)

    agent = make_agent(FormsFill, SYSTEM)
    result: FormsFill | None = None
    err = ""
    for _ in range(_PLAN_RETRY):
        candidate = run_sync(agent, prompt).output
        try:
            result = _validate(candidate)
            break
        except ValueError as exc:
            err = str(exc)
            prompt = prompt + f"\n\n上一次输出未通过校验（错误：{err}），请修正后重新输出。"
    if result is None:
        raise FormsFillError(f"forms 填写失败：两次输出均未通过校验（最后错误：{err}）")

    errors = run_fill_plan(str(out), str(out), _ops_of(result))
    rounds = 0
    while errors and rounds < _FIX_ROUNDS:
        rounds += 1
        fix_prompt = prompt + ("\n\n【上次 plan 执行报错，请只修正报错条目，"
                               "输出修正后的完整 plan】\n" + "\n".join(errors[:30]))
        result = _validate(run_sync(agent, fix_prompt).output)
        errors = run_fill_plan(str(out), str(out), _ops_of(result))
    if errors:
        raise FormsFillError(f"forms 填写失败：报错修正轮次耗尽（仍 {len(errors)} 条，"
                             f"如 {errors[0]}）")
    return {"forms_docx_path": str(out)}
