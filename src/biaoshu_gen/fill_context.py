"""fill 节点公共驱动：预填确定值 + 预注入上下文 + 共享 prompt 后缀。

三个 fill 节点（forms/commercial/deviation）差异仅在于：输出字段名、附加输入、
有无"模板须含某小节"门槛、业务企业资料。统一收敛到 run_fill_node 一个驱动。
"""
import logging
from pathlib import Path

from docx import Document

from .docx_io import body_children_count, template_has_section
from .fill_skill import (
    dump_fill_points, fill_all_blanks, fill_blank_before_label, fill_label_blank,
)
from .harness import HarnessTask, prepare_agent_workspace, run_harness_task
from .kb import KnowledgeBase
from .schemas import GlobalFacts, from_yaml_file
from .state import BidState, run_dir

# 小节判定/组装锚定关键词的单一注册表（gate 与 assemble 共用，避免两处定义漂移）
log = logging.getLogger(__name__)

# 切片小于该 body 元素数视为"无可填内容"(如 3 元素章节封面),跳过 LLM 填充
MIN_FILLABLE_CHILDREN = 5

SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "commercial": ("商务部分", "商务"),
    "deviation": ("偏离表", "偏离"),
}

# 已知值字段 -> 模板中可能出现的标签同义词。
# 配合 fill_all_blanks 的标签边界护栏（:40-41），同义词不会误中 地址/电话 等邻近字段：
# 匹配须到分隔符/括号/段末为止，故 "投标人" 命中 投标人：/投标人（签章）：，不命中 投标人地址：。
FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "项目名称": ("项目名称",),
    "项目编号": ("项目编号", "政府采购编号", "采购代理编号", "采购编号"),
    "采购计划备案号": ("采购计划备案号",),
    "采购人名称": ("采购人名称",),
    "投标人": ("投标人", "投标人名称", "投标单位", "报价单位", "供应商名称", "单位名称"),
    "法定代表人": ("法定代表人", "法人代表"),
    "统一社会信用代码": ("统一社会信用代码", "信用代码"),
}

# 共享 prompt 后缀：取值优先级 + 预填提示（三节点统一，代码侧追加，避免三份 prompt 各自维护）
VALUE_PRIORITY = """- **取值优先级**：项目名称/编号/备案号/采购人等取 facts.yaml 的 template_fields（其次 metadata.yaml）；
  企业名称/法人/信用代码取 facts.yaml 的 company_name/legal_person/credit_code"""
PREFILL_NOTE = "【系统已预填字段（勿在 PLAN 中重复填写；发现遗漏才补）】\n"


def load_facts(state: BidState) -> GlobalFacts:
    """读取 03_facts.yaml（用户编辑优先）；缺失回退 state.facts。"""
    f = run_dir(state) / "03_facts.yaml"
    if f.exists():
        return from_yaml_file(GlobalFacts, f)
    return state.facts or GlobalFacts()


def prefill_summary(prefilled: dict[str, int]) -> list[str]:
    """预填结果 -> prompt 摘要行(["项目名称×3",…]),展示格式集中一处。"""
    return [f"{field}×{n}" for field, n in prefilled.items()]


def prefill_known(doc: Document, state: BidState) -> dict[str, int]:
    """在已打开的模板文档上预填确定值（项目/编号/备案号/投标人/法人/信用代码）。

    值侧来自 facts（template_fields + 企业资料）与 metadata，标签侧走 FIELD_SYNONYMS
    三种文体各扫一遍；返回 {字段: 填写处数}(调用方经 prefill_summary 转展示串,
    fill_forms 按键名直接判断覆盖,不解析展示串)。
    """
    facts = load_facts(state)
    tf = facts.template_fields
    md = state.metadata
    values: dict[str, str] = {
        "项目名称": tf.get("项目名称") or (md.project_name if md else ""),
        "项目编号": tf.get("项目编号") or (md.project_no if md else ""),
        "采购计划备案号": tf.get("采购计划备案号", ""),
        "采购人名称": tf.get("采购人名称", ""),
        "投标人": facts.company_name,
        "法定代表人": facts.legal_person,
        "统一社会信用代码": facts.credit_code,
    }
    filled: dict[str, int] = {}
    for field, synonyms in FIELD_SYNONYMS.items():
        value = values[field]
        if not value:
            continue
        total = 0
        for syn in synonyms:
            n = fill_label_blank(doc, syn, value)   # 段内任意位置(句中括号/同段多标签)
            if n == 0:
                n = fill_all_blanks(doc, syn, value)  # 回退段首语义(含「投标人（签章）：」形态)
            total += n + fill_blank_before_label(doc, syn, value)  # __(标签) 文体
        if total:
            filled[field] = total
    return filled


def build_fill_context(state: BidState, tpl_doc: Document | None = None) -> str:
    parts: list[str] = []
    d = run_dir(state)

    if tpl_doc is not None:
        parts.append("【模板可填点地图（dump_fill_points 输出；段落 [i](线)=带填空线，表格 [Ti]=表头）】\n"
                     + dump_fill_points(tpl_doc))
    else:
        tpl = Path(state.template_docx_path) if state.template_docx_path else Path()
        if tpl.exists():
            parts.append("【模板可填点地图（dump_fill_points 输出；段落 [i](线)=带填空线，表格 [Ti]=表头）】\n"
                         + dump_fill_points(Document(str(tpl))))

    facts = d / "03_facts.yaml"
    if facts.exists():
        parts.append("【facts.yaml 全文（企业资料/模板字段/承诺以此为准）】\n"
                     + facts.read_text(encoding="utf-8"))

    metadata = d / "01_parse" / "metadata.yaml"
    if metadata.exists():
        parts.append("【metadata.yaml 全文】\n" + metadata.read_text(encoding="utf-8"))

    images = KnowledgeBase.load(Path(state.kb_dir)).image_paths()
    if images:
        parts.append("【kb 图片绝对路径（插图 op 的 img 参数用这些；禁止读取图片内容）】\n"
                     + "\n".join(f"- {p.resolve()}" for p in images))

    return "\n\n".join(parts)


def resolve_template_src(state: BidState, part: str | None) -> str:
    """fill 节点的模板源:优先对应 part(四分拆产物),缺失回退整模板。"""
    if part and state.template_parts.get(part) and Path(state.template_parts[part]).exists():
        return state.template_parts[part]
    return state.template_docx_path or ""


def fill_ws_subdir(bucket: str, ws_key: str = "") -> str:
    """fill 工作区子目录的唯一推导点(run_dir 相对):主桶用桶名,附加段用 run 键隔离。"""
    return f"06_fill/{ws_key or bucket}"


def run_with_extras(state: BidState, bucket: str, core) -> dict:
    """fill 节点统一入口:主流程填充首 run + 同桶附加段各跑一次独立工作区。

    core 签名 (state, ws_key="") -> dict;返回 updates 并附 extra_products。
    单个附加段失败不拖垮整体(记 warning,装配回退该段原始 part)。
    """
    updates = core(state)
    extras: dict[str, str] = {}
    if updates.get(f"{bucket}_docx_path"):
        try:
            from .nodes.split_template import load_entries, read_parts_yaml  # 避免环
            entries = [e for e in load_entries(read_parts_yaml(run_dir(state)))
                       if e["bucket"] == bucket and not e.get("primary")]
        except Exception:
            entries = []
        for e in entries:
            sub = state.model_copy(update={"template_parts": {bucket: e["path"]}})
            try:
                up = core(sub, ws_key=e["key"])
            except Exception as exc:
                log.warning("[%s] 附加段 %s 填充失败(%s),装配将回退原始 part",
                            bucket, e["key"], exc)
                continue
            path = up.get(f"{bucket}_docx_path")
            if path:
                extras[e["key"]] = path
        if extras:
            log.info("[%s] %d 个附加区间已完成独立填充", bucket, len(extras))
    if extras:
        updates["extra_products"] = extras
    return updates


def run_fill_node(state: BidState, *, subdir: str, output_field: str, output_name: str,
                  extra_inputs: list[tuple[Path, str]], system: str,
                  build_user_prompt,
                  required_keyword: str | None = None,
                  part: str | None = None,
                  ws_key: str = "") -> dict:
    """fill 三节点公共驱动：门槛判断 -> 工作区 -> 预填确定值 -> 预注入上下文 -> harness。

    build_user_prompt(output) -> str 由调用方构造（forms 需企业资料）。
    part 指定四分拆 bucket 时工作区模板用对应 part,缺失回退整模板。
    ws_key:附加段隔离工作区名(fill_ws_dir 唯一推导)。
    """
    tpl_src = resolve_template_src(state, part)
    if not tpl_src:
        print(f"ℹ 无响应模板，跳过 {subdir} 节点。")
        return {output_field: ""}
    if part:
        subdir = fill_ws_subdir(part, ws_key)
    using_part = tpl_src != (state.template_docx_path or "")
    if using_part:                              # 切片过小=无可填内容(如章节封面 3 元素):
        n_children = body_children_count(tpl_src)
        if n_children < MIN_FILLABLE_CHILDREN:  # 跳过填充——flash 曾强行从 tender.md
            print(f"ℹ {subdir} part 仅 {n_children} 元素,无可填内容,跳过(防复述扩写)。")
            return {output_field: ""}           # 扩写成整章,白烧 LLM 还需守卫兜底
    if required_keyword and not using_part and \
            not template_has_section(Path(tpl_src), required_keyword):
        print(f"ℹ 响应模板中无「{required_keyword}」，跳过 {subdir} 节点。")
        return {output_field: ""}

    ws = prepare_agent_workspace(state, subdir, extra_inputs, template_src=tpl_src)
    out = ws / output_name
    doc = Document(str(ws / "标书模板.docx"))               # 只解析一次：预填 + 地图共用
    prefilled = prefill_known(doc, state)
    doc.save(str(ws / "标书模板.docx"))

    prompt = (system + "\n\n" + build_user_prompt(str(out))
              + "\n\n" + build_fill_context(state, tpl_doc=doc)
              + "\n\n" + VALUE_PRIORITY)
    if prefilled:
        prompt += "\n\n" + PREFILL_NOTE + "\n- ".join(prefill_summary(prefilled))
    run_harness_task(HarnessTask(prompt=prompt, cwd=ws, expected_outputs=[out]))
    return {output_field: str(out)}
