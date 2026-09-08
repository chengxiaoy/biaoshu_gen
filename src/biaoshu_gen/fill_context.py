"""fill 节点公共支撑：预填确定值 + 预注入上下文 + 共享 prompt 后缀。

fill 两节点（forms/deviation）共用的取值/预填/上下文原语；forms 侧的程序化
plan + harness 兜底编排在 nodes/fill_forms.py，偏离表在 nodes/deviation_table.py。
"""
import logging
from pathlib import Path

from docx import Document

from .fill_skill import (
    dump_fill_points, fill_all_blanks, fill_blank_before_label, fill_label_blank,
)
from .ledger import build
from .schemas import GlobalFacts, from_yaml_file
from .state import BidState, run_dir

# 小节判定/组装锚定关键词的单一注册表（gate 与 assemble 共用，避免两处定义漂移）
log = logging.getLogger(__name__)

# 同桶附加段的并行填充线程数（免费档限流，压保守）
_EXTRA_WORKERS = 3

SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "deviation": ("偏离表", "偏离"),
}

# 模板可填点地图的 prompt 头（build_fill_context 两处复用）。
# 图例按真实 run（run-20260908-095225 FormsFill）暴露的踩坑点编写：
# 跳号/下标不进 op、已预填段自动跳过、括号占位走 replace、表格空列表与 row/col 语义。
# 填空统一走 label（blank 已并入）：有无线均可填、全命中、已填自动跳过。
FILL_POINT_MAP_INTRO = (
    "【模板可填点地图】模板切片内全部可填点的索引（空段落与纯正文段已省略，只列可填点，"
    "故下标有跳号；下标仅供阅读对照，op 不接收下标，执行一律按文本匹配）：\n"
    "- 段落行形如 [i](线) 开头文本（截断 50 字）：\n"
    "  · (线) = 该段含下划线填空位（值落在线上并保留余线）；无 (线) 的标签段同样"
    "可填——值直接跟在标签后\n"
    "  · 标签文本直接作 label（抄到「标签+冒号」为止，勿带 tab、空格或已填的旧值）；"
    "填全部命中，标签后已是实义文本（已填过）的命中自动跳过——同文本多段（如多份"
    "承诺书的签章行）一条 label 即可全覆盖\n"
    "  · 「（项目名称）」「（采购人名称）」等括号占位：用 replace 把括号连同占位词"
    "整体替换为实际值\n"
    "  · 签字/盖章/日期落款的段落：跳过，不要对其发 op\n"
    "- 表格行形如 [Tk] 表头各列 | … （N 行）：同表多格**必须**用 table 按行批量填"
    "（table_header 照抄地图 [Tk] 后的表头文本；rows 每个内层 list 是一行按列对位，"
    "null=跳过该格，start_row 默认 1=表头后首行，行数不足自动加行）；散落个别格子才用"
    " cell（row/col 从 0 起，0=表头行）；金额等人工填写项与缺失资料**不发 op**（占位值"
    "会被丢弃），null 跳过即可；== 表格 == 之下无条目 = 本切片没有表格，勿发 cell/table"
)


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
        parts.append(FILL_POINT_MAP_INTRO + "\n\n" + dump_fill_points(tpl_doc))
    else:
        tpl = Path(state.template_docx_path) if state.template_docx_path else Path()
        if tpl.exists():
            parts.append(FILL_POINT_MAP_INTRO + "\n\n"
                         + dump_fill_points(Document(str(tpl))))

    facts = d / "03_facts.yaml"
    if facts.exists():
        parts.append("【facts.yaml 全文（企业资料/模板字段/承诺以此为准）】\n"
                     + facts.read_text(encoding="utf-8"))

    metadata = d / "01_parse" / "metadata.yaml"
    if metadata.exists():
        parts.append("【metadata.yaml 全文】\n" + metadata.read_text(encoding="utf-8"))

    ledger = build(Path(state.kb_dir))
    if ledger.texts:
        # 企业信息摘要：商务内容（资质/案例/人员/业绩）程序化路径的唯一事实来源
        parts.append("【企业信息摘要（资质/案例/人员/业绩只能引用其中实有内容；单源截断）】\n"
                     + "\n\n".join(f"### 来源：{name}\n{text[:600]}"
                                    for name, text in ledger.texts))
    if ledger.images:
        parts.append("【kb 图片绝对路径（插图 op 的 img 参数用这些；禁止读取图片内容）】\n"
                     + "\n".join(f"- {p.resolve()}" for p in ledger.images))

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
    """fill 节点统一入口:主段 + 同桶附加段各跑一次独立工作区，全部并行提交。

    core 签名 (state, ws_key="") -> dict;返回 updates 并附 extra_products。
    主段与附加段互相独立(工作区 ws_key 隔离、模板源各取自己的 part)，同时提交
    线程池——附加段不再等主段跑完(每段一次完整 LLM 调用,串行时 N+1 段即 N+1 倍
    耗时),总耗时从 sum 降为 max。免费档限流,并发压在 _EXTRA_WORKERS。
    单个附加段失败不拖垮整体(记 warning,装配回退该段原始 part)。
    """
    if not resolve_template_src(state, bucket):
        return core(state)          # 无模板:主段自行 skip 返回空路径,附加段无从谈起

    try:
        from .nodes.split_template import load_entries, read_parts_yaml  # 避免环
        entries = [e for e in load_entries(read_parts_yaml(run_dir(state)))
                   if e["bucket"] == bucket and not e.get("primary")]
    except Exception:
        entries = []

    def _run_extra(e: dict) -> tuple[str, str] | None:
        sub = state.model_copy(update={"template_parts": {bucket: e["path"]}})
        try:
            up = core(sub, ws_key=e["key"])
        except Exception as exc:
            log.warning("[%s] 附加段 %s 填充失败(%s),装配将回退原始 part",
                        bucket, e["key"], exc)
            return None
        path = up.get(f"{bucket}_docx_path")
        return (e["key"], path) if path else None

    extras: dict[str, str] = {}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=_EXTRA_WORKERS) as pool:
        main = pool.submit(core, state)                     # 主段(默认工作区)
        extra_futs = {e["key"]: pool.submit(_run_extra, e) for e in entries}
        updates = main.result()
        for key, fut in extra_futs.items():
            r = fut.result()
            if r:
                extras[r[0]] = r[1]
    if extras:
        log.info("[%s] %d 个附加区间已完成独立填充", bucket, len(extras))
        updates["extra_products"] = extras
    return updates
