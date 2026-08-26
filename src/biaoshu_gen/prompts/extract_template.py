"""extract_template 节点 prompt(LLM 定界)：定位响应文件格式章节的起止块。"""

SYSTEM = "你是投标文件结构分析师，负责在招标文件中定位响应文件（投标文件）格式章节的边界。"

TEMPLATE = """以下是招标文档按顺序编号的内容块（[序号] 内容摘要；表格压缩为一行）：

{blocks_text}

任务：找出"投标文件/响应文件的格式"章节（即给出投标函、报价表、偏离表等空白格式的章节）的块边界。

判定规则：
1. start_index：格式章节标题所在块的序号（如「第七章 投标文件的格式」「第五章 响应文件组成」）
2. end_index：格式章节之后下一个章级标题（第X章）所在块的序号；格式章节直到文档末尾则为 null
3. 目录页中的条目不是章节标题；正文中引用的章节名不算
4. 只返回 JSON：{{"start_index": <整数>, "end_index": <整数或null>}}
"""


def build_user_prompt(blocks_text: str) -> str:
    return TEMPLATE.format(blocks_text=blocks_text)
