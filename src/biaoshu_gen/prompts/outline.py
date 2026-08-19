"""技术方案目录生成节点 prompt：三级提纲（不参考响应模板——模板中不含技术方案格式要求）。"""

SYSTEM = "你是专业的标书编写专家，负责生成投标文件技术标部分的目录结构。"

TEMPLATE = """根据以下项目需求与技术评分要求，生成投标文件中技术标部分的三级目录结构。

【标书需求】
{requirements}

【技术评分要求（目录必须逐项响应）】
{technical_rules}

【全局事实设定】
{facts}

要求：
1. 目录结构全面覆盖技术标的所有必要章节
2. 章节名称专业、准确，符合投标文件规范
3. 一级目录名称须与技术评分要求中的章节/评分项名称一致；技术评分要求中没有明确名称时，结合其内容生成一级目录名称
4. 一共三级目录：一级章（sections）、二级节（children）、三级小节（children）；三级小节是正文撰写单位
5. 每个节点给出 description（该节写作要点，一句话）
6. 仅三级小节给出 target_words（预期字数，整数）；全书总字数控制在 25000~40000 字
7. id 按层级编号："1"、"1.1"、"1.1.1"

字段长度硬约束（超长会被系统拒绝）：
- title：不超过 25 个汉字，不得包含写作建议、括号说明或换行
- description：不超过 60 个汉字
"""


def build_user_prompt(requirements: str, technical_rules: str, facts: str) -> str:
    return TEMPLATE.format(
        requirements=requirements or "（无）",
        technical_rules=technical_rules or "（无）",
        facts=facts or "（无）",
    )
