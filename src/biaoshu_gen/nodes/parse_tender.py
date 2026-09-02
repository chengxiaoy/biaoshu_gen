"""节点 1：招标文件解析--按目录分节阅读：关键词路由 -> 分组抽取 -> 合并落盘。"""
from pathlib import Path

import yaml
from pydantic import BaseModel

from ..config import get_settings
from ..docx_io import DocxSection, docx_to_sections, needs_structure_fallback, sections_to_markdown
from ..models import make_agent, run_sync
from ..prompts.parse_tender import SYSTEM_EXTRACT, build_extract_prompt
from ..schemas import (
    InvalidationItems, ScoringStandards, TenderMetadata, TenderRequirements,
    to_yaml_file,
)
from ..state import BidState, run_dir
from .structure import rebuild_sections

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
                 "交货", "质保", "合同草案",
                 # 竞争性磋商系术语（真实样本：项目名称/预算全在「第一章 磋商邀请」）
                 "磋商邀请", "磋商公告", "截止"),
    "requirements": ("采购需求", "采购清单", "项目概况", "技术要求", "实施要求",
                     "建设内容", "交付", "预期成果"),
    "scoring": ("评标", "评分", "资格审查", "评审"),
    "invalidation": ("无效", "废标", "拒收", "扣分", "偏离", "停止评标"),
}
# 内容级兜底（仅对列出的组）：关键表格常由非标题段落引导（如「附页6 评审因素和标准」
# 「第一节 磋商须知前附表」），整表 flush 进上一节，标题路由覆盖不到。
# 正文含签名特征即强制入组；每个元组的全部子串都命中才算签名
# （("评分因素","评分标准") 双条件防「演示评分内容」类误报）。
_CONTENT_SIGNS: dict[str, tuple[tuple[str, ...], ...]] = {
    "scoring": (
        ("评审因素和标准",),
        ("评分因素", "评分标准"),
    ),
    "metadata": (
        ("条款名称", "编列内容规定"),   # 磋商/招标须知前附表（真实截止时间/预算所在）
    ),
}
_MAX_BATCH_CHARS = 24000


def classify_sections(sections: list[DocxSection]) -> dict[str, list[int]]:
    """确定性目录路由：标题或任一上级章节标题命中关键词即入组；
    另按正文签名兜底（评分表/前附表挂在无关键词标题下的情形）。"""
    by_group: dict[str, list[int]] = {g: [] for g in GROUPS}
    ancestors: list[tuple[int, str]] = []      # (level, title) 章/节上下文栈
    for i, s in enumerate(sections, 1):
        while ancestors and ancestors[-1][0] >= s.level:
            ancestors.pop()
        titles = [t for _, t in ancestors] + [s.title]
        for group, keywords in _GROUP_KEYWORDS.items():
            if any(k in t for t in titles for k in keywords):
                by_group[group].append(i)
        for group, signs_list in _CONTENT_SIGNS.items():
            if any(all(sign in s.content for sign in signs) for signs in signs_list):
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

    # ⓪ 结构兜底：标题样式过少/形同虚设时，LLM 重建章节边界（routing.yaml 留痕）
    mode = "heading"
    if needs_structure_fallback(sections):
        sections = rebuild_sections(Path(state.tender_path))
        mode = "llm_rebuild"

    # ① 目录路由：代码侧关键词匹配（含上级章节继承），零 LLM 成本
    by_group = classify_sections(sections)

    # ② 分组抽取：全部(组,批次)任务相互独立,线程池并发(#69)——
    # 4 组×多批次此前纯串行,是 parse 阶段的主要时延;每任务独立 agent(线程安全)
    from concurrent.futures import ThreadPoolExecutor

    results: dict[str, BaseModel] = {g: tp() for g, (tp, _) in GROUPS.items()}
    tasks: list[tuple[str, str, object]] = []           # (group, prompt, agent)
    for group, (tp, desc) in GROUPS.items():
        group_sections = [sections[i - 1] for i in by_group[group]]
        if not group_sections:
            continue
        for batch in _batches(group_sections):
            prompt = build_extract_prompt(desc, "\n\n".join(
                (f"{'#' * s.level} {s.title}\n\n" if s.level else "") + s.content
                for s in batch))
            tasks.append((group, prompt, make_agent(tp, SYSTEM_EXTRACT)))

    with ThreadPoolExecutor(max_workers=min(get_settings().parse_concurrency,
                                            max(1, len(tasks)))) as ex:
        submitted = [(group, ex.submit(run_sync, agent, prompt))
                     for group, prompt, agent in tasks]
        per_group: dict[str, list] = {}
        for group, fut in submitted:                   # 按提交序收果:合并语义确定
            per_group.setdefault(group, []).append(fut.result().output)
    for group, objs in per_group.items():
        results[group] = _merge(objs) if len(objs) > 1 else objs[0]

    # ③ 落盘（tender.md 复用已切好的 sections，不二次解析；routing.yaml 路由透明化）
    d = run_dir(state) / "01_parse"
    d.mkdir(parents=True, exist_ok=True)
    (d / "tender.md").write_text(sections_to_markdown(sections), encoding="utf-8")
    routing = {"structure_mode": mode,
               **{g: [f"{i}. {sections[i - 1].title}" for i in idx] for g, idx in by_group.items()}}
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
