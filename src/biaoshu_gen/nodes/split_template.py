"""节点 2b：响应模板四分拆（fill 前置）。

有标题模板走确定性规则（标题关键词归类），无标题模板 LLM 兜底分段；
物理拆分用 clip_docx_keep 整包副本多区间保留。产出 parts/ 四份 part docx
与 parts.yaml 清单（bucket → path/sections/first_element_index，order 为
文档原序），state.template_parts 供 fill 各节点取用与 assemble 顺序拼接。
"""
from pathlib import Path

import yaml
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from ..docx_io import _HEADING_RE, _full_text, clip_docx_keep, iter_numbered_blocks
from ..models import make_agent, run_sync       # noqa: F401  (测试 monkeypatch st.make_agent)
from ..prompts.split_template import SYSTEM, build_user_prompt
from ..schemas import TemplateSplit
from ..state import BidState, run_dir

_RETRY_TIMES = 2   # 首次 + 校验失败重试一次

BUCKETS = ("deviation", "technical", "forms", "commercial")
PART_NAMES = {"deviation": "偏离表部分.docx", "technical": "技术方案部分.docx",
              "forms": "表格填写部分.docx", "commercial": "商务填写部分.docx"}
# 按序命中,先到先得;commercial 为 catch-all 不设关键词
KEYWORDS = {
    "deviation": ("偏离",),
    "technical": ("实施方案", "技术方案", "技术部分"),
    "forms": ("投标函", "响应声明", "报价", "价格", "一览表", "开标", "资格"),
}


class TemplateSplitError(RuntimeError):
    """模板拆分失败（LLM 两次输出均未通过校验）。"""


def classify_title(title: str) -> str:
    for bucket in BUCKETS[:-1]:
        if any(kw in title for kw in KEYWORDS[bucket]):
            return bucket
    return "commercial"


def _split_by_headings(doc) -> dict[str, list[int]] | None:
    """有标题模板:沿 body 子元素走,Heading 段切换当前 bucket。

    返回 bucket -> 元素下标列表;全文无 Heading 时返回 None(交 LLM 兜底)。
    """
    assign: dict[str, list[int]] = {}
    sections: dict[str, list[str]] = {}
    current = "commercial"
    saw_heading = False
    for i, child in enumerate(doc.element.body.iterchildren()):
        if child.tag == qn("w:p"):
            para = Paragraph(child, doc)
            text = _full_text(para).strip()
            if _HEADING_RE.match((para.style.name or "").strip()) and text:
                saw_heading = True
                current = classify_title(text)
                sections.setdefault(current, []).append(text)
        assign.setdefault(current, []).append(i)
    if not saw_heading:
        return None
    assign["_sections"] = sections                       # type: ignore[assignment]
    return assign


def _validate_split(split: TemplateSplit, n_blocks: int) -> list[tuple[int, int, str]]:
    """校验 spans:界内、bucket 合法、按序不重叠。返回 [(start_blk, end_blk_excl, bucket)]。"""
    spans: list[tuple[int, int, str]] = []
    prev_end = 0
    for s in split.spans:
        if s.bucket not in BUCKETS:
            raise ValueError(f"未知 bucket: {s.bucket}")
        if not 0 <= s.start_index < n_blocks:
            raise ValueError(f"start_index {s.start_index} 越界(共 {n_blocks} 块)")
        e = s.end_index
        if e is None or e > n_blocks:
            e = n_blocks
        elif not s.start_index < e:
            raise ValueError(f"区间 [{s.start_index},{e}) 非法(需 start < end)")
        if s.start_index < prev_end:
            raise ValueError("spans 重叠或乱序")
        prev_end = e
        spans.append((s.start_index, e, s.bucket))
    return spans


def _split_by_llm(doc, tpl: Path) -> dict[str, list[int]]:
    """无标题模板:块化 -> 单次 LLM 分段 -> 硬校验(失败带错重试一次)。"""
    blocks = iter_numbered_blocks(doc)
    n_children = len(list(doc.element.body.iterchildren()))
    blocks_text = "\n".join(f"[{b.index}] {b.stub}" for b in blocks)
    agent = make_agent(TemplateSplit, SYSTEM)
    prompt = build_user_prompt(blocks_text)
    spans: list[tuple[int, int, str]] | None = None
    err = ""
    for _ in range(_RETRY_TIMES):
        result: TemplateSplit = run_sync(agent, prompt).output
        try:
            spans = _validate_split(result, len(blocks))
            break
        except ValueError as exc:
            err = str(exc)
            prompt = build_user_prompt(blocks_text) + (
                f"\n\n上一次输出未通过校验(错误:{err}),请修正后重新输出。")
    if spans is None:
        raise TemplateSplitError(f"模板拆分失败:两次输出均未通过校验(最后错误:{err})")

    # 块序号区间 -> 元素下标区间;未覆盖块归 commercial
    assign: dict[str, list[int]] = {"commercial": []}
    sections: dict[str, list[str]] = {}
    covered: list[tuple[int, int, str]] = []
    for start_blk, end_blk, bucket in spans:
        start_el = blocks[start_blk].element_index
        end_el = blocks[end_blk].element_index if end_blk < len(blocks) else n_children
        covered.append((start_el, end_el, bucket))
        sections.setdefault(bucket, []).append(blocks[start_blk].stub[:40])
    cursor = 0
    all_el = list(range(n_children))
    for start_el, end_el, bucket in covered:
        assign.setdefault("commercial", []).extend(all_el[cursor:start_el])
        assign.setdefault(bucket, []).extend(all_el[start_el:end_el])
        cursor = end_el
    assign["commercial"].extend(all_el[cursor:])
    assign["_sections"] = sections                        # type: ignore[assignment]
    return assign


def read_parts_yaml(run: Path) -> dict:
    """读 parts.yaml(缺失返回空 dict,fill/assemble 依此回退旧路径)。"""
    f = run / "02_template" / "parts" / "parts.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


def load_entries(manifest: dict) -> list[dict]:
    """取装配用的有序 run 条目;老格式(无 entries)从 order+parts 合成单条目。"""
    if manifest.get("entries"):
        return sorted(manifest["entries"], key=lambda e: e["first_element_index"])
    out = []
    for key in manifest.get("order", []):
        info = manifest.get("parts", {}).get(key) or {}
        if info.get("path"):
            out.append({"key": key, "bucket": key, "path": info["path"],
                        "sections": info.get("sections", []),
                        "first_element_index": info.get("first_element_index", 0)})
    return sorted(out, key=lambda e: e["first_element_index"])


def _runs_from_assign(assign: dict[str, list[int]]) -> list[tuple[str, list[int], str]]:
    """按元素下标轴合并相邻同桶 → 连续区间 runs[(bucket, indexes, 末标题)]。

    同桶不相邻(交错模板)会产生同桶多个 run——这是 software 招标文件
    ((四)(五)商务内容嵌在投标函与资格之间)致装配乱序的根因,run 粒度保留原序。
    """
    pairs: list[tuple[int, str]] = []
    for bucket in BUCKETS:
        for i in assign.get(bucket, []):
            if i >= 0:
                pairs.append((i, bucket))
    pairs.sort()
    runs: list[tuple[str, list[int]]] = []
    for i, bucket in pairs:
        if runs and runs[-1][0] == bucket:
            runs[-1][1].append(i)
        else:
            runs.append((bucket, [i]))
    # 附各 run 收尾时的最近标题(展示用);近似即可
    return [(b, idxs, "") for b, idxs in runs]


def split_template_node(state: BidState) -> dict:
    tpl = Path(state.template_docx_path) if state.template_docx_path else Path()
    if not tpl.exists():
        print("ℹ 无响应模板，跳过模板拆分。")
        return {"template_parts": {}}

    parts_dir = run_dir(state) / "02_template" / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    doc = Document(str(tpl))
    assign = _split_by_headings(doc)
    if assign is None:
        assign = _split_by_llm(doc, tpl)
    sections: dict[str, list[str]] = assign.pop("_sections")  # type: ignore[arg-type]

    runs = _runs_from_assign(assign)

    manifest: dict[str, dict] = {}
    template_parts: dict[str, str] = {}
    entries: list[dict] = []
    seen: dict[str, int] = {}                              # 桶 -> 已见 run 数
    for bucket, indexes, _tail in runs:
        nth = seen.get(bucket, 0)
        seen[bucket] = nth + 1
        key = bucket if nth == 0 else f"{bucket}_{nth + 1}"
        stem = Path(PART_NAMES[bucket]).stem
        name = PART_NAMES[bucket] if nth == 0 else f"{stem}_{nth + 1}.docx"
        dest = parts_dir / name
        clip_docx_keep(tpl, dest, indexes)
        first = min(indexes)
        entry = {"key": key, "bucket": bucket, "path": str(dest),
                 "sections": [s for s in sections.get(bucket, [])][:len(runs)],
                 "first_element_index": first}
        entries.append(entry)
        if nth == 0:                                       # 首段沿用旧键(兼容 fill 取用)
            template_parts[bucket] = str(dest)
            manifest[bucket] = {"path": str(dest), "sections": sections.get(bucket, []),
                                "first_element_index": first}

    order = sorted(manifest, key=lambda b: manifest[b]["first_element_index"])
    (parts_dir / "parts.yaml").write_text(
        yaml.safe_dump({"order": order, "parts": manifest,
                        "entries": sorted(entries, key=lambda e: e["first_element_index"])},
                       allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return {"template_parts": template_parts}
