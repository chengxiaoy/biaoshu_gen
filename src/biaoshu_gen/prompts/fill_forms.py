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

执行流程（**材料已预注入本 prompt 末尾，禁止再读任何文件探查**；invalidation.yaml 可按需读一次）：
1. 基于 prompt 末尾的【模板可填点地图】与【facts/metadata/图片路径】，直接写**一个**驱动脚本：
   from fill_skill import run_fill_plan
   PLAN = [
     {"op": "blank", "prefix": "项目名称：", "value": "……"},          # 下划线填空（值在线上）
     {"op": "cell", "table_header": ["序号", "服务期"], "row": 1, "col": 1, "value": "……"},
     {"op": "replace", "prefix": "致：", "old": "（采购人名称）", "new": "……"},
     {"op": "picture", "prefix": "备注：", "img": "<预注入的图片绝对路径>", "width": 4.8, "caption": "附：营业执照"},
     {"op": "append", "prefix": "投标人名称：", "value": "……"},       # 无填空线的段末追加
   ]
   errors = run_fill_plan('标书模板.docx', '{output}', PLAN)
   print(errors or 'OK')
2. errors 非空时只修正报错条目重跑（通常一次收敛）；产物为 {output}

要求：
- 逐条核对 invalidation.yaml：签字/盖章/附件/格式要求必须满足或预留位置
- 图片：img 用 kb.md 中的绝对路径，**实际插入**（picture op）而非写路径；禁止读取/查看图片内容
- 格式保持：不得删除/隐藏模板中的下划线、表格线、签字/盖章占位
"""


def build_user_prompt(output: str, company_name: str = "", legal_person: str = "",
                      credit_code: str = "") -> str:
    # 用 replace 而非 format：正文含 PLAN 字典花括号，format 会误解析
    return (TEMPLATE
            .replace("{output}", output)
            .replace("{company_name}", company_name or "（facts.yaml 缺失）")
            .replace("{legal_person}", legal_person or "（facts.yaml 缺失）")
            .replace("{credit_code}", credit_code or "（facts.yaml 缺失）"))
