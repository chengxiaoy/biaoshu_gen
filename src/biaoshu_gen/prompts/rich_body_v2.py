"""rich_body_v2 prompt：与 LLM 交互以二级节为单位，返回按三级格式（feedback #76）。

单元 = 一个二级节（直挂一级的叶子以一级为界成组）。一次调用覆盖该节全部
三级小节；返回须逐条 sec_id 对位，不得遗漏、不得新增。
"""

UNIT_PRESET_SYSTEM = """你是标书编写专家，判断一个二级节下各三级小节是否需要图表。

判定原则：
1. 参数对比、清单罗列、指标响应、进度计划适合 table（Markdown 表格）
2. 架构、流程、拓扑、时序、组织结构适合 figure（mermaid 图）
3. 纯论述性、规范性、承诺性文字不需要图表（type=none），宁缺毋滥
4. score 为需求强度 0~1：与招标技术要求/评分标准关联越紧分数越高；可有可无不高于 0.5
5. needs 必须覆盖输入清单中的每一个三级小节，sec_id 逐条对应
"""

UNIT_PRESET_TEMPLATE = """判断以下二级节中各三级小节的图表需求。

【二级节】{sec_id} {sec_title}
【二级节说明】{sec_desc}

【三级小节清单】
{leaf_lines}
"""

UNIT_BODY_SYSTEM = """你是专业的标书编写专家，为技术标撰写一个二级节的全部三级小节正文。

要求：
1. 内容专业、准确，与小节标题和写作要点保持一致
2. 这是技术方案，不是宣传报告：朴实无华、不假大空，严格依据全局事实设定，禁止与事实冲突的承诺
3. 同节各小节之间自然衔接，避免内容重复
4. 直接返回 Markdown 正文（可用列表），不生成小节标题（标题由系统按目录拼装）
5. sections 必须覆盖输入清单的每一个三级小节，sec_id 逐条对应，不得遗漏、不得新增
"""

UNIT_BODY_TEMPLATE = """撰写以下二级节全部三级小节的正文。

【二级节】{sec_id} {sec_title}
【二级节说明】{sec_desc}

【三级小节清单（逐条撰写，sec_id 对应返回）】
{leaf_lines}

【目标字数】各小节按清单中标注的目标字数（非空白字符计，允许 ±30% 偏差）

【全书目录（上下文，用于保持前后衔接）】
{tree}

【全局事实设定（必须严格遵守）】
{facts}

【企业知识库参考材料】
{kb}

{feedback}"""


def _leaf_lines(unit_leaves) -> str:
    return "\n".join(
        f"- {l.id} {l.title}（约 {l.target_words} 字）：{l.description or '（无）'}"
        for l in unit_leaves)


def build_unit_preset_prompt(sec, unit_leaves) -> str:
    return UNIT_PRESET_TEMPLATE.format(
        sec_id=sec.id, sec_title=sec.title, sec_desc=sec.description or "（无）",
        leaf_lines=_leaf_lines(unit_leaves))


def build_unit_body_prompt(sec, unit_leaves, tree: str, facts: str,
                           kb: str, feedback: str = "") -> str:
    fb = f"【上一轮审核意见（必须修复本单元被点名小节的这些问题）】\n{feedback}\n\n" if feedback else ""
    return UNIT_BODY_TEMPLATE.format(
        sec_id=sec.id, sec_title=sec.title, sec_desc=sec.description or "（无）",
        leaf_lines=_leaf_lines(unit_leaves), tree=tree or "（无）",
        facts=facts or "（无）", kb=kb or "（无）", feedback=fb)
