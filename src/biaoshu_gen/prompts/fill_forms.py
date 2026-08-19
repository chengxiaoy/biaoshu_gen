"""投标函+报价文件+货物一览表+资格证明文件填写 prompt（harness）。"""

SYSTEM = "你是投标文件填写专员，负责严格按招标文件要求填写表格类投标文件。"

TEMPLATE = """工作区文件：
- tender.md：招标文件全文；invalidation.yaml：废标项+扣分项
- metadata.yaml：标书元数据；facts.yaml：全局事实设定（含投标人企业资料）
- kb.md：企业知识库摘要（含营业执照等图片绝对路径）
- 标书模板.docx：响应文件模板（若有）

投标人企业资料（必填项，一律取自 facts.yaml）：
- 企业/投标人名称：{company_name}
- 法定代表人：{legal_person}
- 统一社会信用代码：{credit_code}

任务：用 python-docx 创建表格类填写文件 {output}，包含：
1. 投标函：格式按招标文件要求，含项目名称/编号/投标有效期；报价数字一律写"〔待人工填写〕"
2. 报价文件/报价一览表：结构齐全，金额单元格写"〔待人工填写〕"
3. 货物一览表：按招标采购清单与 metadata 逐项列出
4. 资格证明文件：引用 kb.md 中的资质与图片材料路径（如营业执照）

要求：
- 上述企业资料必须填入投标函/资格证明对应位置；若为 mock 占位值（含"待替换"），照填并在交付说明中注明需人工替换
- 逐条核对 invalidation.yaml：签字/盖章/附件/格式要求必须满足或预留位置
- 表格规范、单元格可编辑；完成后文件必须存在且非空
- 【重要】kb.md 中列出的图片材料（营业执照等）只需在文档中引用其文件名/路径，禁止用工具查看或读取图片文件（会超出消息缓冲导致任务崩溃）
"""


def build_user_prompt(output: str, company_name: str = "", legal_person: str = "",
                      credit_code: str = "") -> str:
    return TEMPLATE.format(
        output=output,
        company_name=company_name or "（facts.yaml 缺失）",
        legal_person=legal_person or "（facts.yaml 缺失）",
        credit_code=credit_code or "（facts.yaml 缺失）",
    )
