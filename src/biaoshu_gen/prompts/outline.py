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

输出要求：
- sections：章节列表（title、target_words 预期字数、key_points 要点）
- 章节粒度适中（5~10 章），总字数符合投标常见体量（total_words 为各章之和）
"""


def build_user_prompt(requirements: str, technical_rules: str, facts: str, template_md: str) -> str:
    return TEMPLATE.format(
        requirements=requirements or "（无）",
        technical_rules=technical_rules or "（无）",
        facts=facts or "（无）",
        template_md=template_md or "（无）",
    )
