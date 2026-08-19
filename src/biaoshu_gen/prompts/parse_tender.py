"""招标文件解析节点 prompt：分组抽取（分节阅读，避免整篇长上下文）。

目录路由为代码侧关键词匹配（见 nodes/parse_tender.classify_sections），无 LLM 分类调用。
"""

SYSTEM_EXTRACT = "你是资深软件投标分析师。只依据给出的章节内容抽取信息，原文没有的留空/空列表，不得臆造。"

EXTRACT_TEMPLATE = """从以下招标文件章节内容中抽取「{group_desc}」：

{sections_text}

要求：
- 只依据原文，不得臆造
- 若本批次无相关信息：字符串字段留空、列表字段返回空列表
- 废标项/扣分项需给出原文依据（source_quote）"""


def build_extract_prompt(group_desc: str, sections_text: str) -> str:
    return EXTRACT_TEMPLATE.format(group_desc=group_desc, sections_text=sections_text)
