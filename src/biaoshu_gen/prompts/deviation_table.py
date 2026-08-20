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
- **工具优先**：工作区已放置 fill_skill.py（表格填写/下划线填空/插图原语，前缀锚定）。
  优先 `from fill_skill import fill_blank, fill_cell, insert_picture_after` 使用；下划线空白一律用 fill_blank（值填在线上）
- **取值优先级**：项目名称/编号等取 facts.yaml 的 template_fields；企业资料取 facts.yaml 的
  company_name/legal_person/credit_code；投标响应与 facts.yaml 承诺一致
- 格式保持：填写时**不得删除/隐藏模板中的下划线（＿＿＿）、表格线**等原有格式元素，保持模板原格式
- 图片处理：需要插图时用 insert_picture_after **实际插入**；仍**禁止读取/查看图片内容**（会超出消息缓冲），依据文件名判断
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.format(output=output)
