"""投标模板抽取节点 prompt（harness）。"""

SYSTEM = "你是投标文件结构分析师，负责拆解招标文件对响应文件（标书）的格式要求。"

TEMPLATE = """工作区说明：
- tender.md：招标文件全文（Markdown）
- {template_line}

任务：拆解招标文件要求的响应文件格式，产出两个文件：

1. template.md -- 响应文件模板：
   - 标书完整目录树（按招标文件要求的组成部分，如投标函、报价文件、货物一览表、
     资格证明文件、技术方案、偏离表、商务响应等）
   - 每个组成部分的填写要求（格式、签字盖章、附件材料）
   - 标注各部分属于"表格类填写"还是"文档类编写"
2. report.md -- 用户查阅报告：目录结构、各部分要求摘要、招标文件原文依据

要求：
- 只依据招标文件原文，不得虚构组成部分
- {template_note}
- 两个文件均为 UTF-8 编码，完成后必须存在且非空
"""


def build_user_prompt(has_template_docx: bool) -> str:
    if has_template_docx:
        template_line = "标书模板.docx：随招标文件提供的响应文件模板（参考用）"
        template_note = "对照 标书模板.docx 的结构，在 report.md 中说明模板与招标要求的对应关系"
    else:
        template_line = "（未提供响应文件模板 docx）"
        template_note = "没有模板 docx 时，完全依据招标文件文字要求构建目录树"
    return TEMPLATE.format(template_line=template_line, template_note=template_note)
