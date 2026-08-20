"""fill 节点公共驱动：预填确定值 + 预注入上下文 + 共享 prompt 后缀。

三个 fill 节点（forms/commercial/deviation）差异仅在于：输出字段名、附加输入、
有无"模板须含某小节"门槛、业务企业资料。统一收敛到 run_fill_node 一个驱动。
"""
from pathlib import Path

from docx import Document

from .docx_io import template_has_section
from .fill_skill import dump_fill_points, fill_all_blanks
from .harness import HarnessTask, prepare_agent_workspace, run_harness_task
from .kb import KnowledgeBase
from .schemas import GlobalFacts, from_yaml_file
from .state import BidState, run_dir

# 小节判定/组装锚定关键词的单一注册表（gate 与 assemble 共用，避免两处定义漂移）
SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "commercial": ("商务部分", "商务"),
    "deviation": ("偏离表", "偏离"),
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


def prefill_known(doc: Document, state: BidState) -> list[str]:
    """在已打开的模板文档上预填确定值（项目/编号/备案号/投标人/法人/信用代码）。

    返回已填字段摘要（如 "项目名称×3"），供 prompt 告知 harness 勿重复填写。
    """
    facts = load_facts(state)
    tf = facts.template_fields
    md = state.metadata
    pairs: list[tuple[str, str]] = []

    def add(labels: tuple[str, ...], value: str) -> None:
        if value:
            pairs.extend((lb, value) for lb in labels)

    add(("项目名称",), tf.get("项目名称") or (md.project_name if md else ""))
    add(("项目编号",), tf.get("项目编号") or (md.project_no if md else ""))
    add(("采购计划备案号",), tf.get("采购计划备案号", ""))
    add(("采购人名称",), tf.get("采购人名称", ""))
    add(("投标人",), facts.company_name)          # 覆盖 投标人（签章）/投标人名称/投标人（盖单位章）
    add(("法定代表人",), facts.legal_person)
    add(("统一社会信用代码",), facts.credit_code)

    summary: list[str] = []
    for label, value in pairs:
        n = fill_all_blanks(doc, label, value)
        if n:
            summary.append(f"{label}×{n}")
    return summary


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


def run_fill_node(state: BidState, *, subdir: str, output_field: str, output_name: str,
                  extra_inputs: list[tuple[Path, str]], system: str,
                  build_user_prompt,
                  required_keyword: str | None = None) -> dict:
    """fill 三节点公共驱动：门槛判断 -> 工作区 -> 预填确定值 -> 预注入上下文 -> harness。

    build_user_prompt(output) -> str 由调用方构造（forms 需企业资料）。
    """
    if not state.template_docx_path:
        print(f"ℹ 无响应模板，跳过 {subdir} 节点。")
        return {output_field: ""}
    if required_keyword and not template_has_section(Path(state.template_docx_path),
                                                     required_keyword):
        print(f"ℹ 响应模板中无「{required_keyword}」，跳过 {subdir} 节点。")
        return {output_field: ""}

    ws = prepare_agent_workspace(state, subdir, extra_inputs)
    out = ws / output_name
    doc = Document(str(ws / "标书模板.docx"))               # 只解析一次：预填 + 地图共用
    prefilled = prefill_known(doc, state)
    doc.save(str(ws / "标书模板.docx"))

    prompt = (system + "\n\n" + build_user_prompt(str(out))
              + "\n\n" + build_fill_context(state, tpl_doc=doc)
              + "\n\n" + VALUE_PRIORITY)
    if prefilled:
        prompt += "\n\n" + PREFILL_NOTE + "\n- ".join(prefilled)
    run_harness_task(HarnessTask(prompt=prompt, cwd=ws, expected_outputs=[out]))
    return {output_field: str(out)}
