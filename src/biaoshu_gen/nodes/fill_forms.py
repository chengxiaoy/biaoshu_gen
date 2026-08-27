"""节点 7：投标函+报价文件+货物一览表+资格证明文件（非 harness）。

LLM 直出填写 plan（FillOp 列表），python 经 fill_skill.run_fill_plan 单次执行；
执行报错即失败(管线层软失败放行,不回炉——回炉曾致慢与逐轮丢 op)。
确定值（项目名称等）仍由代码预填。
skip gate 与 forms_docx_path 契约不变。
"""
import shutil
from pathlib import Path

from docx import Document

from ..business import ensure_business_fields
from ..fill_context import (
    FIELD_SYNONYMS, PREFILL_NOTE, VALUE_PRIORITY, build_fill_context, prefill_known,
    resolve_template_src,
)
from ..fill_skill import run_fill_plan
from ..models import make_agent, run_sync       # noqa: F401  (测试 monkeypatch ff.make_agent)
from ..prompts.fill_forms import SYSTEM, build_user_prompt
from ..schemas import FormsFill
from ..state import BidState, run_dir

_OP_KINDS = {"blank", "label", "replace", "cell", "picture", "append"}
_PLAN_RETRY = 2      # plan 校验失败重试一次
_FIX_ROUNDS = 0      # 执行报错修正轮次上限


class FormsFillError(RuntimeError):
    """forms 填写失败（plan 校验不过或报错修正轮次耗尽）。"""


def _call_llm(agent, prompt: str):
    """run_sync 包装:网关偶发 finish_reason=error 等异常重试一次,仍失败转 FormsFillError。"""
    import time as _time
    import logging

    log = logging.getLogger(__name__)
    for attempt in range(2):
        try:
            return run_sync(agent, prompt).output
        except FormsFillError:
            raise
        except Exception as e:                 # 网关/端点偶发错误(超时/finish_reason=error)
            if attempt:
                raise FormsFillError(f"forms 填写失败：LLM 调用异常（{e}）") from e
            log.warning("[forms] LLM 调用异常(%s),5s 后重试", e)
            _time.sleep(5)
    raise FormsFillError("forms 填写失败：LLM 调用异常")


def _validate(result: FormsFill) -> FormsFill:
    if not result.plan:
        raise ValueError("plan 为空")
    for i, op in enumerate(result.plan):
        if op.op not in _OP_KINDS:
            raise ValueError(f"第 {i + 1} 条 op 未知: {op.op}")
    return result


def _ops_of(result: FormsFill) -> list[dict]:
    return [op.model_dump(exclude_none=True) for op in result.plan]


def _ops_of_list(ops) -> list[dict]:
    return [op.model_dump(exclude_none=True) for op in ops]


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
    base = ws / "标书模板_预填.docx"           # 预填后的干净底稿:修复轮重放前重置用
    doc = Document(str(tpl_src))              # 只解析一次：预填 + 地图共用
    prefilled = prefill_known(doc, state)
    doc.save(str(base))
    shutil.copyfile(base, out)

    prompt = (SYSTEM + "\n\n"
              + build_user_prompt(str(out), facts.company_name, facts.legal_person,
                                  facts.credit_code)
              + "\n\n" + build_fill_context(state, tpl_doc=doc)
              + "\n\n" + VALUE_PRIORITY)
    if prefilled:
        prompt += "\n\n" + PREFILL_NOTE + "\n- ".join(prefilled)

    agent = make_agent(FormsFill, SYSTEM)
    import logging
    log = logging.getLogger(__name__)
    log.info("[forms] 底稿=%s 预填=%s", tpl_src, prefilled or "无")
    result: FormsFill | None = None
    err = ""
    for _ in range(_PLAN_RETRY):
        candidate = _call_llm(agent, prompt)
        try:
            result = _validate(candidate)
            break
        except ValueError as exc:
            err = str(exc)
            prompt = prompt + f"\n\n上一次输出未通过校验（错误：{err}），请修正后重新输出。"
    if result is None:
        raise FormsFillError(f"forms 填写失败：两次输出均未通过校验（最后错误：{err}）")

    # 预填已覆盖的字段(同义词级):模型仍发对应 label op 时跳过——空位已被填,
    # 执行只会报"未命中";值以 facts 预填为准(VALUE_PRIORITY 约定)
    done_labels = {syn for f in (s.split("×")[0] for s in prefilled)
                   for syn in FIELD_SYNONYMS.get(f, ())}
    kept = [op for op in result.plan
            if not (op.op == "label" and op.label in done_labels)]
    if len(kept) < len(result.plan):
        log.info("[forms] %d 条 label op 已被预填覆盖,跳过", len(result.plan) - len(kept))

    errors = run_fill_plan(str(out), str(out), _ops_of_list(kept))
    log.info("[forms] plan 共 %d 条 op,执行报错 %d 条%s", len(kept), len(errors),
             "" if not errors else "\n  " + "\n  ".join(errors[:10]))
    rounds = 0
    while errors and rounds < _FIX_ROUNDS:
        rounds += 1
        print(f"⚠ forms plan 执行报错 {len(errors)} 条，第 {rounds}/{_FIX_ROUNDS} 轮修正：\n"
              + "\n".join(f"  - {e}" for e in errors[:10]))
        fix_prompt = prompt + ("\n\n【上次 plan 执行报错，请只修正报错条目，"
                               "输出修正后的完整 plan】\n" + "\n".join(errors[:30]))
        result = _validate(_call_llm(agent, fix_prompt))
        shutil.copyfile(base, out)             # 重置到预填底稿,整计划干净重放
        errors = run_fill_plan(str(out), str(out), _ops_of(result))
    if errors:
        # 用户裁决(2026-08-27):个别 op 报错(签章行/无下划线段等不可填目标)不弃产物,
        # 记 error.log 供人工补;节点级异常(LLM挂/校验失败)仍抛出走软失败
        errfile = run_dir(state) / "06_fill" / "fill_forms.error.log"
        errfile.write_text("plan 执行报错（产物已保留,以下空位需人工补）:\n"
                           + "\n".join(f"- {e}" for e in errors), encoding="utf-8")
        log.warning("[forms] %d 条 op 报错已记 %s,产物保留", len(errors), errfile)
    log.info("[forms] 产物 %s(%d 字节)", out, out.stat().st_size)
    return {"forms_docx_path": str(out)}
