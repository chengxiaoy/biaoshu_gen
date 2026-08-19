"""投标模板抽取节点 prompt（harness）：从招标文件提取响应文件模板。"""

SYSTEM = "你是投标文件结构分析师，负责从招标文件中提取响应文件（标书）的格式模板。"

TEMPLATE = """工作区文件：
- tender.md：招标文件全文（Markdown）
- 招标文件.docx：招标文件原件（格式的权威来源）
{template_line}

任务：从招标文件（尤其"投标文件的格式"章节）提取响应文件模板，产出三个文件：

1. 标书模板.docx —— 可填写的响应模板 docx：
   - 用 python-docx 从 招标文件.docx 中提取"投标文件的格式"章节的全部内容
     （投标函、开标一览表、分项报价表、法定代表人身份证明/授权书、资格证明文件、
     商务部分、技术部分等格式页与表格），按原有顺序与格式组装成独立文档
   - 保留原有标题层级、表格结构与签字/盖章占位，不改动格式
   - 待填内容以空白/占位符呈现，不填写任何投标信息
2. template.md —— 响应文件模板说明：完整目录树 + 每部分填写要求 + 标注"表格类填写/文档类编写"
3. report.md —— 用户查阅报告：目录结构、各部分要求摘要、招标文件原文依据

要求：
- 只依据招标文件原文，不得虚构组成部分
- {template_note}
- 三个文件均为 UTF-8（docx 除外），完成后必须存在且非空
"""


def build_user_prompt(has_template_docx: bool) -> str:
    if has_template_docx:
        template_line = "- 投标模板参考.docx：随招标文件提供的响应模板（结构参考）"
        template_note = "对照 投标模板参考.docx 的结构，在 report.md 中说明与招标要求的对应关系"
    else:
        template_line = "-（未随附响应模板 docx）"
        template_note = "没有随附模板时，完全依据招标文件文字要求与格式章节构建"
    return TEMPLATE.format(template_line=template_line, template_note=template_note)
