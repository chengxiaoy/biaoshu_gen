"""偏离表填写 prompt（harness）：有模板按模板格式、无模板按招标要求新建。"""

SYSTEM = "你是投标文件填写专员，负责编制投标偏离表。"

TEMPLATE = """工作区文件：
- 标书模板.docx：响应文件模板（若有，其中的偏离表是**优先格式依据**）
- tender.md：招标文件全文；requirements.yaml：标书需求；scoring.yaml：评分标准
- invalidation.yaml：废标项+扣分项；facts.yaml：全局事实设定；kb.md：企业知识库摘要

任务：编制偏离表，产出 {output}：
- 若 标书模板.docx 中存在偏离表：**打开它**，严格按模板表格格式（列头/列序/标题）填写，
  沿用原有结构仅填充/追加数据行
- 若模板中无偏离表：按招标文件对偏离表的要求（列头通常为：序号/招标文件要求/投标响应/偏离说明）
  新建表格
- 逐条覆盖 requirements.yaml 中的技术要求、实施要求与商务参数（含交货日期/质保期）
- 投标响应必须与 facts.yaml 的承诺一致；严禁出现负偏离
- invalidation.yaml 中被扣分评分的条目必须逐条入表

完成后文件必须存在且非空。
- 【重要】kb.md 中列出的图片材料（营业执照等）只需在文档中引用其文件名/路径，禁止用工具查看或读取图片文件（会超出消息缓冲导致任务崩溃）
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.format(output=output)
