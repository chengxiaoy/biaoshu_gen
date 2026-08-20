"""fill 节点的预注入上下文 + 确定值预填：模板可填点地图 + facts/metadata + kb 图片路径。

目的：
- 预注入：harness 一上来就拥有全部信息，把"读文件探查"轮次压到零；
- 预填：项目名称/编号/投标人/法人/信用代码等**确定值**由代码直接填进模板副本，
  harness 只生成剩余非平凡内容，压缩 PLAN 体积（巨型生成轮）。
"""
from pathlib import Path

from docx import Document

from .fill_skill import dump_fill_points, fill_all_blanks
from .kb import KnowledgeBase
from .schemas import GlobalFacts, from_yaml_file
from .state import BidState, run_dir


def _load_facts(state: BidState) -> GlobalFacts:
    f = run_dir(state) / "03_facts.yaml"
    if f.exists():
        return from_yaml_file(GlobalFacts, f)
    return state.facts or GlobalFacts()


def prefill_known(tpl_path: Path, state: BidState) -> list[str]:
    """在模板副本上自动预填确定值（项目/编号/备案号/投标人/法人/信用代码等）。

    返回已填字段摘要（如 "项目名称×3"），供 prompt 告知 harness 勿重复填写。
    """
    facts = _load_facts(state)
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

    doc = Document(str(tpl_path))
    summary: list[str] = []
    for label, value in pairs:
        n = fill_all_blanks(doc, label, value)
        if n:
            summary.append(f"{label}×{n}")
    if summary:
        doc.save(str(tpl_path))
    return summary


def build_fill_context(state: BidState, template_path: Path | None = None) -> str:
    parts: list[str] = []
    d = run_dir(state)

    tpl = template_path or (Path(state.template_docx_path) if state.template_docx_path else Path())
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
