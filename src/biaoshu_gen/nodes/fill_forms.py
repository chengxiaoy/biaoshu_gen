"""节点 7：其余填写部分整体填写（原 fill_forms + commercial 合并，feedback #78）。

先程序化填写：LLM 直出填写 plan（FillOp 列表），python 经 fill_skill.run_fill_plan
单次执行（快、稳定、不依赖 harness 通道）；再 harness 兜底：plan 两次校验失败、
LLM 通道异常或执行报错时，由 claude agent 在同工作区打开既有产物补填——
兜底失败不弃产物（记 error.log 放行，程序化成果保留）。
同桶多区间附加段经 run_with_extras 各跑独立工作区(ws_key 隔离,互不覆盖)。
确定值（项目名称等）仍由代码预填。skip gate 与 forms_docx_path 契约不变。
"""
import json as _json
import logging
import shutil
from pathlib import Path

from docx import Document

from ..business import ensure_business_fields
from ..fill_context import (
    FIELD_SYNONYMS, PREFILL_NOTE, VALUE_PRIORITY, build_fill_context, fill_ws_subdir,
    prefill_known, prefill_summary, resolve_template_src, run_with_extras,
)
from ..fill_skill import run_fill_plan
from ..harness import HarnessTask, environment_notes, prepare_agent_workspace, run_harness_task
from ..models import make_agent, run_sync       # noqa: F401  (测试 monkeypatch ff.make_agent)
from ..prompts.fill_forms import (
    SYSTEM, build_fallback_prompt, build_user_prompt, FALLBACK_SYSTEM,
)
from ..schemas import FillOp, FormsFill
from ..state import BidState, run_dir, write_node_error

log = logging.getLogger(__name__)

_PLAN_RETRY = 2      # plan 校验失败重试一次


class FormsFillError(RuntimeError):
    """forms 填写失败（plan 校验不过或报错修正轮次耗尽）。"""


# 人工填写/待补的占位标记:含这些字样的 op 不执行(真实 run 曾输出 30+ 条占位 op 白烧
# 输出 token 且污染产物)——prompt 已约定不发,此处兜底过滤,空位保持原样留给人工。
_MANUAL_MARKS = ("待人工填写", "待补", "待人工补")


def _has_manual_mark(op: FillOp) -> bool:
    """op 的任一文本字段(含 table 的 rows 二维数组)含占位标记即为人工填写 op。"""
    return any(m in _json.dumps(op.model_dump(exclude_none=True), ensure_ascii=False)
               for m in _MANUAL_MARKS)


def _call_llm(agent, prompt: str):
    """run_sync 包装:网关偶发 finish_reason=error 等异常重试一次,仍失败转 FormsFillError。"""
    import time
    for attempt in range(2):
        try:
            return run_sync(agent, prompt).output
        except FormsFillError:
            raise
        except Exception as e:                 # 网关/端点偶发错误(超时/finish_reason=error)
            if attempt:
                raise FormsFillError(f"forms 填写失败：LLM 调用异常（{e}）") from e
            log.warning("[forms] LLM 调用异常(%s),5s 后重试", e)
            time.sleep(5)
    raise FormsFillError("forms 填写失败：LLM 调用异常")


def _validate(result: FormsFill) -> FormsFill:
    """op 合法性已由 FillOp 分型 union(discriminator) 在输出校验层保证,
    这里只挡空 plan(合法但无意义,直接走 _PLAN_RETRY 修正)。"""
    if not result.plan:
        raise ValueError("plan 为空")
    return result


def _ops_of(ops) -> list[dict]:
    return [op.model_dump(exclude_none=True) for op in ops]


def _harness_fallback(state: BidState, ws_key: str, out: Path,
                      errors: list[str], plan_failed: bool) -> None:
    """harness 兜底：程序化路径的遗留（plan 失败 / 报错 op）由 agent 在产物上补填。

    工作区与程序化路径共用（prepare_agent_workspace 幂等投放 tender/scoring/kb/
    fill_skill），地图基于**当前产物**（报错空位都在其中）。产物缺失校验天然
    满足（out 已存在），成败由 agent 实际补填决定。
    """
    run = run_dir(state)
    ws = prepare_agent_workspace(
        state, fill_ws_subdir("forms", ws_key),
        extra_inputs=[(run / "01_parse" / "scoring.yaml", "scoring.yaml")],
        template_src=resolve_template_src(state, "forms") or None)
    prompt = (FALLBACK_SYSTEM + "\n\n"
              + build_fallback_prompt(str(out), errors, plan_failed)
              + "\n\n" + build_fill_context(state, tpl_doc=Document(str(out)))
              + "\n\n" + VALUE_PRIORITY + "\n\n" + environment_notes())
    run_harness_task(HarnessTask(prompt=prompt, cwd=ws, expected_outputs=[out]))


def _forms_core(state: BidState, ws_key: str = "") -> dict:
    facts = ensure_business_fields(state)       # 企业/法人/信用代码缺失则 mock 并回写 facts.yaml
    tpl_src = resolve_template_src(state, "forms")
    if not tpl_src:
        print("ℹ 无响应模板，跳过 fill_forms 节点。")
        return {"forms_docx_path": ""}

    run = run_dir(state)
    ws = run / fill_ws_subdir("forms", ws_key)
    ws.mkdir(parents=True, exist_ok=True)
    out = ws / "forms.docx"
    base = ws / "标书模板_预填.docx"           # 预填后的干净底稿:harness 兜底重置参考
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
        prompt += "\n\n" + PREFILL_NOTE + "\n- ".join(prefill_summary(prefilled))

    agent = make_agent(FormsFill, SYSTEM)
    log.info("[forms] 底稿=%s 预填=%s", tpl_src, prefilled or "无")

    # 预填已覆盖的字段(同义词级):模型仍发对应 label op 时跳过——空位已被填,
    # 执行只会报"未命中";值以 facts 预填为准(VALUE_PRIORITY 约定)
    done_labels = {syn for field in prefilled for syn in FIELD_SYNONYMS.get(field, ())}

    def drop_covered(ops: list[FillOp]) -> list[FillOp]:
        kept = []
        n_manual = 0
        for op in ops:
            if op.op == "label" and op.label in done_labels:
                continue
            if _has_manual_mark(op):        # 「〔待人工填写〕/〔待补〕」占位 op:不发不执行,留给人工
                n_manual += 1
                continue
            kept.append(op)
        dropped = len(ops) - len(kept)
        if dropped:
            log.info("[forms] %d 条 op 被过滤(%d 条 label 已预填覆盖,%d 条人工占位值)",
                     dropped, dropped - n_manual, n_manual)
        return kept

    # ---- 先程序化：LLM 直出 plan -> python 确定性执行 ----
    result: FormsFill | None = None
    errors: list[str] = []
    err = ""
    try:
        for _ in range(_PLAN_RETRY):
            candidate = _call_llm(agent, prompt)
            try:
                result = _validate(candidate)
                break
            except ValueError as exc:
                err = str(exc)
                prompt = prompt + f"\n\n上一次输出未通过校验（错误：{err}），请修正后重新输出。"
        if result is not None:
            kept = drop_covered(result.plan)
            errors = run_fill_plan(str(out), str(out), _ops_of(kept))
            log.info("[forms] plan 共 %d 条 op,执行报错 %d 条%s", len(kept), len(errors),
                     "" if not errors else "\n  " + "\n  ".join(errors[:10]))
    except FormsFillError as exc:              # LLM 通道挂：与 plan 失败同路走兜底
        err = str(exc)
        log.warning("[forms] %s,转 harness 兜底", err)

    # ---- 再 harness 兜底：plan 失败 / LLM 挂 / 执行报错 ----
    plan_failed = result is None
    if plan_failed or errors:
        reason = err if plan_failed else f"{len(errors)} 条 op 执行报错"
        print(f"⚠ forms 程序化填写遗留（{reason}），转 harness 兜底补填…")
        try:
            _harness_fallback(state, ws_key, out, errors, plan_failed)
            log.info("[forms] harness 兜底完成,产物 %s", out)
        except Exception as exc:               # 兜底也失败:不弃产物,记 error.log 供人工补
            errfile = write_node_error(state, "fill_forms",
                                       f"harness 兜底失败（产物保留程序化填写成果）: {exc}\n"
                                       + (f"程序化失败原因: {err}" if plan_failed else
                                          "报错 op:\n" + "\n".join(f"- {e}" for e in errors)))
            log.warning("[forms] 兜底失败已记 %s,产物保留", errfile)
    log.info("[forms] 产物 %s(%d 字节)", out, out.stat().st_size)
    return {"forms_docx_path": str(out)}


def fill_forms_node(state: BidState) -> dict:
    return run_with_extras(state, "forms", _forms_core)
