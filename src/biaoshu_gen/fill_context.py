"""fill 节点的预注入上下文：模板可填点地图 + facts/metadata + kb 图片路径。

目的：harness 一上来就拥有全部信息，把"读文件探查"轮次压到零，
工作流收敛为 写驱动脚本 -> 跑 -> 修报错 三步。
"""
from pathlib import Path

from docx import Document

from .fill_skill import dump_fill_points
from .kb import KnowledgeBase
from .state import BidState, run_dir


def build_fill_context(state: BidState) -> str:
    parts: list[str] = []
    d = run_dir(state)

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
