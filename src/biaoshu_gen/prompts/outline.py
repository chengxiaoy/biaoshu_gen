"""技术方案目录生成节点 prompt。"""

SYSTEM = "你是投标技术方案架构师，目录必须覆盖招标技术要求并响应技术评分标准。"

TEMPLATE = """为技术方案生成章节目录。

【标书需求】
{requirements}

【技术评分标准（逐条必须在目录中有所响应）】
{technical_rules}

【全局事实设定】
{facts}

【响应文件模板结构（目录须与之衔接）】
{template_md}

输出要求（字段长度是硬约束，超长会被系统拒绝）：
- sections：5~10 章的章节列表
- title：章节标题，不超过 25 个汉字，不得包含写作建议、括号说明或换行
- target_words：本章预期字数（整数）
- key_points：本章要点，最多 4 条、每条不超过 30 个汉字（短语，不是段落）
- total_words：各章 target_words 之和
"""


def build_user_prompt(requirements: str, technical_rules: str, facts: str, template_md: str) -> str:
    return TEMPLATE.format(
        requirements=requirements or "（无）",
        technical_rules=technical_rules or "（无）",
        facts=facts or "（无）",
        template_md=template_md or "（无）",
    )
