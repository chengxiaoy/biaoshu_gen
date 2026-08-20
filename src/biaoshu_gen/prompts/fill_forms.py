"""投标函+报价文件+货物一览表+资格证明文件填写 prompt（harness）：从模板副本填写。"""

SYSTEM = "你是投标文件填写专员，负责按响应模板的既有格式填写表格类投标文件。"

TEMPLATE = """工作区文件：
- 标书模板.docx：响应文件模板（其中的投标函/报价文件/货物一览表/资格证明等格式是**唯一格式依据**）
- tender.md：招标文件全文；invalidation.yaml：废标项+扣分项
- metadata.yaml：标书元数据；facts.yaml：全局事实设定（含投标人企业资料）
- kb.md：企业知识库摘要（含营业执照等图片绝对路径）

投标人企业资料（必填项，一律取自 facts.yaml）：
- 企业/投标人名称：{company_name}
- 法定代表人：{legal_person}
- 统一社会信用代码：{credit_code}

任务：**打开 标书模板.docx**，按模板中投标函/报价文件/货物一览表/资格证明文件的**原有结构与格式**逐项填写，
产出 {output}：
- 在模板副本中沿用原有表格/函件格式，仅填充内容；不新建其他格式的文档，不删减/调整模板原有章节
- 投标函：按模板格式填写，含项目名称/编号/投标有效期；报价数字一律写"〔待人工填写〕"
- 报价文件/开标一览表/分项报价表：沿用模板表格结构，金额单元格写"〔待人工填写〕"
- 货物一览表：按招标采购清单与 metadata 逐项填入模板对应表格
- 资格证明文件：按模板小节填入企业资料与 kb.md 资质，并实际插入相应图片（见图片处理要求）
- 企业资料若为 mock 占位值（含"待替换"），照填并在交付说明中注明需人工替换

要求：
- **工具优先**：工作区已放置 fill_skill.py（表格填写/下划线填空/插图原语，前缀锚定免逐段探查）。
  优先 `from fill_skill import fill_blank, fill_cell, replace_in_para, insert_picture_after` 使用；
  下划线空白一律用 fill_blank（值填*在线上*，不会附加到下划线之后），不要自己按下标改 run
- **取值优先级**：项目名称/编号/备案号/采购人等取 facts.yaml 的 template_fields（其次 metadata.yaml）；
  企业名称/法人/信用代码取 facts.yaml 的 company_name/legal_person/credit_code
- 逐条核对 invalidation.yaml：签字/盖章/附件/格式要求必须满足或预留位置
- 完成后文件必须存在且非空
- 图片处理：需要插图（营业执照/资质证书等）时用 insert_picture_after **实际插入**，不要只写路径；
  仍**禁止读取/查看图片内容**（会超出消息缓冲），依据文件名判断是否需要插入
- 格式保持：填写时**不得删除/隐藏模板中的下划线（＿＿＿）、表格线、签字/盖章占位**等原有格式元素，保持模板原格式
"""


def build_user_prompt(output: str, company_name: str = "", legal_person: str = "",
                      credit_code: str = "") -> str:
    return TEMPLATE.format(
        output=output,
        company_name=company_name or "（facts.yaml 缺失）",
        legal_person=legal_person or "（facts.yaml 缺失）",
        credit_code=credit_code or "（facts.yaml 缺失）",
    )
