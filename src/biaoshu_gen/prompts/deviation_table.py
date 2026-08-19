"""偏离表填写 prompt（harness）：严格按响应模板中的偏离表格式填写。"""

SYSTEM = "你是投标文件填写专员，负责按响应模板中的偏离表格式填写偏离表。"

TEMPLATE = """工作区文件：
- 标书模板.docx：响应文件模板（其中的偏离表是**唯一格式依据**）
- tender.md：招标文件全文；requirements.yaml：标书需求；scoring.yaml：评分标准
- invalidation.yaml：废标项+扣分项；facts.yaml：全局事实设定；kb.md：企业知识库摘要

任务：**打开 标书模板.docx，找到其中的偏离表**，严格按其表格格式（列头、列序、标题）填写，
产出 {output}：
- 不要新建别的格式的表格；沿用模板中偏离表的原有结构，仅填充/追加数据行
- 逐条覆盖 requirements.yaml 中的技术要求、实施要求与商务参数（含交货日期/质保期）
- 投标响应必须与 facts.yaml 的承诺一致；严禁出现负偏离
- invalidation.yaml 中被扣分评分的条目必须逐条入表

完成后文件必须存在且非空。
- 【重要】kb.md 中列出的图片材料（营业执照等）只需在文档中引用其文件名/路径，禁止用工具查看或读取图片文件（会超出消息缓冲导致任务崩溃）
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.format(output=output)
