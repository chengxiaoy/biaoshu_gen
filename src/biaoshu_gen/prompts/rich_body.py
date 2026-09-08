"""rich_body（图表版正文）prompt：图表需求判定 / 表格与 mermaid 图生成 / 插入位置。"""

# ---------- D：各小节图表需求判定（MediaNeed） ----------

PRESET_SYSTEM = """你是标书编写专家，负责判断技术方案小节是否适合配置表格或图。

判定原则：
1. 参数对比、清单罗列、指标响应、进度计划等内容适合 table（Markdown 表格）
2. 架构、流程、拓扑、时序、组织结构等适合 figure（mermaid 图）
3. 纯论述性、规范性、承诺性文字不需要图表（type=none），宁缺毋滥
4. score 为需求强度 0~1：与招标技术要求/评分标准关联越紧分数越高；可有可无的不高于 0.5
"""

PRESET_TEMPLATE = """判断以下三级小节是否需要图表。

【小节】{sec_id} {title}
【写作要点】{description}
【目标字数】约 {target_words} 字

【全书目录（上下文）】
{tree}
"""


def build_preset_prompt(sec_id: str, title: str, description: str,
                        target_words: int, tree: str = "") -> str:
    return PRESET_TEMPLATE.format(
        sec_id=sec_id, title=title, description=description or "（无）",
        target_words=target_words, tree=tree or "（无）",
    )


# ---------- G：表格 / mermaid 图生成（SectionMedia） ----------

_MEDIA_REQUIREMENT = {
    "table": "media_content 为标准 Markdown 表格：首行表头（≤6 列），第二行 |---|---| 对齐行",
    "figure": "media_content 为 mermaid 代码本体：不要 ``` 围栏、不要解释文字，"
              "以 flowchart TD / sequenceDiagram 等图型关键字开头",
}

MEDIA_SYSTEM = """你是标书图表生成专家，为技术方案小节生成表格或 mermaid 图。

要求：
1. 内容严格取材于给定正文与知识库材料，参数与数值不得虚构；材料没有的数据用（待填）占位
2. media_caption 为简短中文说明（10 字内，不带"表"/"图"字前缀）
3. 图表要脱离正文也能被独立理解，信息不与正文句子简单重复
"""

MEDIA_TEMPLATE = """为以下小节生成一个{media_type}。

【小节】{sec_id} {title}
【写作要点】{description}

【小节正文（取材依据与插入上下文）】
{content}

【企业知识库参考材料】
{kb}

{feedback}输出要求：type={media_type}；{requirement}；media_caption 为标题说明。
"""


def build_media_prompt(sec_id: str, title: str, description: str, media_type: str,
                       content: str, kb: str, feedback: str = "") -> str:
    fb = f"【上一轮生成未通过校验（必须修复）】\n{feedback}\n\n" if feedback else ""
    return MEDIA_TEMPLATE.format(
        sec_id=sec_id, title=title, description=description or "（无）",
        media_type=media_type, content=content or "（无）", kb=kb or "（无）",
        feedback=fb, requirement=_MEDIA_REQUIREMENT[media_type],
    )


# ---------- G：媒体插入位置（InsertPoint） ----------

INSERT_SYSTEM = """你是标书排版助手，为已生成的图表挑选正文中的插入位置。

只输出一个整数 index：媒体块将插入到第 index 段之前（段落从 0 编号，段数 N 时 index 取 0..N，N 表示放在末尾）。
挑选原则：
1. 插到与其内容最相关的段落之前，使图文紧邻
2. 不打断并列结构（编号/列表段落中间不插）
3. 尽量不插在最前（index=0）影响开篇，除非正文只有一段
"""

INSERT_TEMPLATE = """【媒体类型】{media_type}
【图表说明】{caption}

【正文段落（共 {n} 段，按 0..{last} 编号，已截断展示）】
{numbered}
"""


def build_insert_prompt(paragraphs: list[str], media_type: str, caption: str) -> str:
    numbered = "\n".join(
        f"[{i}] {p.strip()[:80]}" for i, p in enumerate(paragraphs) if p.strip()
    )
    n = len(paragraphs)
    return INSERT_TEMPLATE.format(
        media_type=media_type, caption=caption or "（无）",
        n=n, last=n, numbered=numbered,
    )
