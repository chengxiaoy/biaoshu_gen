"""节点 1：招标文件解析--按目录分节阅读：关键词路由 -> 分组抽取 -> 合并落盘。"""
from pathlib import Path

import yaml
from pydantic import BaseModel

from ..docx_io import DocxSection, docx_to_markdown, docx_to_sections
from ..models import make_agent
from ..prompts.parse_tender import SYSTEM_EXTRACT, build_extract_prompt
from ..schemas import (
    InvalidationItems, ScoringStandards, TenderMetadata, TenderRequirements,
    to_yaml_file,
)
from ..state import BidState, run_dir

# 每组抽取的输出类型与说明（进入抽取 prompt）
GROUPS: dict[str, tuple[type[BaseModel], str]] = {
    "metadata": (TenderMetadata,
                 "标书元数据：项目名称/编号、项目背景、投标截止、交货日期、质保期等"),
    "requirements": (TenderRequirements,
                     "标书需求：采购清单、项目概况、技术要求（逐条）、实施要求（逐条）"),
    "invalidation": (InvalidationItems,
                     "废标项+扣分项：逐条给出 kind(废标项|扣分项)/requirement/source_quote"),
    "scoring": (ScoringStandards,
                "评标标准：价格评分规则、商务评分规则（逐条）、技术评分规则（逐条）"),
}

# 代码侧关键词路由：章节标题（含上级章节标题）命中即入组，一个章节可同时属于多组。
# 相比 LLM 分类调用：零成本、毫秒级、确定性，且子章节自动继承章主题（如"第五章 评标办法"下的全部小节）。
_GROUP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "metadata": ("公告", "投标邀请", "前附表", "中标通知", "投标报价", "投标有效期",
                 "交货", "质保", "合同草案"),
    "requirements": ("采购需求", "采购清单", "项目概况", "技术要求", "实施要求",
                     "建设内容", "交付", "预期成果"),
    "scoring": ("评标", "评分", "资格审查"),
    "invalidation": ("无效", "废标", "拒收", "扣分", "偏离", "停止评标"),
}
_MAX_BATCH_CHARS = 24000


def classify_sections(sections: list[DocxSection]) -> dict[str, list[int]]:
    """确定性目录路由：标题或任一上级章节标题命中关键词即入组。"""
    by_group: dict[str, list[int]] = {g: [] for g in GROUPS}
    ancestors: list[tuple[int, str]] = []      # (level, title) 章/节上下文栈
    for i, s in enumerate(sections, 1):
        while ancestors and ancestors[-1][0] >= s.level:
            ancestors.pop()
        titles = [t for _, t in ancestors] + [s.title]
        for group, keywords in _GROUP_KEYWORDS.items():
            if any(k in t for t in titles for k in keywords):
                by_group[group].append(i)
        if s.level:
            ancestors.append((s.level, s.title))
    return {g: sorted(set(idx)) for g, idx in by_group.items()}


def _batches(sections: list[DocxSection]) -> list[list[DocxSection]]:
    """按整节组批（≤_MAX_BATCH_CHARS）；单节超长再按段落硬切。"""
    batches: list[list[DocxSection]] = []
    buf: list[DocxSection] = []
    size = 0
    for s in sections:
        if len(s.content) > _MAX_BATCH_CHARS:
            if buf:
                batches.append(buf)
                buf, size = [], 0
            paras = s.content.split("\n\n")
            acc: list[str] = []
            acc_size = 0
            for para in paras:
                acc.append(para)
                acc_size += len(para)
                if acc_size >= _MAX_BATCH_CHARS:
                    batches.append([DocxSection(s.level, s.title, "\n\n".join(acc))])
                    acc, acc_size = [], 0
            if acc:
                batches.append([DocxSection(s.level, s.title, "\n\n".join(acc))])
            continue
        if size + len(s.content) > _MAX_BATCH_CHARS and buf:
            batches.append(buf)
            buf, size = [], 0
        buf.append(s)
        size += len(s.content)
    if buf:
        batches.append(buf)
    return batches


def _merge(objs: list[BaseModel]) -> BaseModel:
    """同组多批次结果合并：str 取第一个非空；list 拼接去重（保持顺序）。"""
    merged: dict = {}
    for name in type(objs[0]).model_fields:
        values = [getattr(o, name) for o in objs]
        first = values[0]
        if isinstance(first, list):
            seen: set = set()
            out: list = []
            for v in values:
                for item in v:
                    key = item if isinstance(item, str) else (
                        item.model_dump_json() if hasattr(item, "model_dump_json") else str(item))
                    if key not in seen:
                        seen.add(key)
                        out.append(item)
            merged[name] = out
        elif isinstance(first, str):
            merged[name] = next((v for v in values if v), "")
        else:
            merged[name] = values[-1]
    return type(objs[0]).model_validate(merged)


def parse_tender_node(state: BidState) -> dict:
    sections = docx_to_sections(Path(state.tender_path))

    # ① 目录路由：代码侧关键词匹配（含上级章节继承），零 LLM 成本
    by_group = classify_sections(sections)

    # ② 分组抽取：每组只拼接本组章节内容
    results: dict[str, BaseModel] = {}
    for group, (tp, desc) in GROUPS.items():
        group_sections = [sections[i - 1] for i in by_group[group]]
        if not group_sections:
            results[group] = tp()
            continue
        objs = [
            make_agent(tp, SYSTEM_EXTRACT).run_sync(
                build_extract_prompt(desc, "\n\n".join(
                    (f"{'#' * s.level} {s.title}\n\n" if s.level else "") + s.content
                    for s in batch))).output
            for batch in _batches(group_sections)
        ]
        results[group] = _merge(objs) if len(objs) > 1 else objs[0]

    # ③ 落盘（tender.md 全文 + routing.yaml 路由透明化，供后续 harness 节点使用）
    d = run_dir(state) / "01_parse"
    d.mkdir(parents=True, exist_ok=True)
    (d / "tender.md").write_text(docx_to_markdown(Path(state.tender_path)), encoding="utf-8")
    routing = {g: [f"{i}. {sections[i - 1].title}" for i in idx] for g, idx in by_group.items()}
    (d / "routing.yaml").write_text(
        yaml.safe_dump(routing, allow_unicode=True, sort_keys=False), encoding="utf-8")
    to_yaml_file(results["metadata"], d / "metadata.yaml")
    to_yaml_file(results["requirements"], d / "requirements.yaml")
    to_yaml_file(results["invalidation"], d / "invalidation.yaml")
    to_yaml_file(results["scoring"], d / "scoring.yaml")
    return {
        "metadata": results["metadata"],
        "requirements": results["requirements"],
        "invalidation": results["invalidation"],
        "scoring": results["scoring"],
    }
