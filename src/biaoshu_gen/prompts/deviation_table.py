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

执行流程（**严格四步一次成型，禁止逐步探查模板**）：
1. 一条命令拿模板地图（只跑一次）：
   python -c "import docx; from fill_skill import dump_fill_points; print(dump_fill_points(docx.Document('标书模板.docx')))"
2. 读取 requirements.yaml / scoring.yaml / facts.yaml / kb.md（各自读一次即可）
3. 写**一个**驱动脚本：把偏离表逐条响应组织成 PLAN 清单（cell op 按表头定位逐格填写/追加行）后一次运行：
   from fill_skill import run_fill_plan
   PLAN = [
     {"op": "cell", "table_header": ["序号", "招标文件要求"], "row": 1, "col": 0, "value": "1"},
     {"op": "cell", "table_header": ["序号", "招标文件要求"], "row": 1, "col": 2, "value": "无偏离"},
     ...
   ]
   errors = run_fill_plan('标书模板.docx', '{output}', PLAN)
   print(errors or 'OK')
4. errors 非空时只修正报错条目重跑；产物为 {output}

要求：
- **取值优先级**：项目名称/编号等取 facts.yaml 的 template_fields；企业资料取 facts.yaml 的
  company_name/legal_person/credit_code；投标响应与 facts.yaml 承诺一致，严禁负偏离
- 格式保持：不得删除/隐藏下划线、表格线；图片用 picture op 实际插入，禁止读取图片内容
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.replace("{output}", output)  # 花括号安全
