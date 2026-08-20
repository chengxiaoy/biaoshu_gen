"""商务响应文件 prompt（harness）：严格按响应模板的商务部分格式填写。"""

SYSTEM = "你是投标文件填写专员，负责按响应模板的商务部分格式编制商务响应文件。"

TEMPLATE = """工作区文件：
- 标书模板.docx：响应文件模板（其中的"商务部分"是**唯一格式依据**）
- tender.md：招标文件全文；scoring.yaml：评分标准（含商务评分）
- facts.yaml：全局事实设定；metadata.yaml：商务参数；kb.md：企业知识库摘要（资质/案例）
- invalidation.yaml：废标项+扣分项

任务：**打开 标书模板.docx，找到"商务部分"（业绩证明文件/拟派项目团队/其他商务文件等小节）**，
在**该模板副本中**按原有结构填入内容，产出 {output}：
- 在原有小节下插入信息文字，并按需**实际插入** kb.md 中的图片（见图片处理要求），
  不删除、不调整模板原有标题与小节顺序
- 逐条响应商务评分标准与商务参数（交货日期、质保期、付款方式、培训等）
- **严格依据事实填写，不得编造**：所有承诺必须与 facts.yaml 一致；资质/案例/人员/业绩只能引用 kb.md
  中实际存在的内容，kb.md 中没有的信息不得虚构，缺失处留空或注明"〔待补〕"
- 满足 invalidation.yaml 中关于格式/签字/盖章的要求

完成后文件必须存在且非空。
- **工具优先**：工作区已放置 fill_skill.py（表格填写/下划线填空/插图原语，前缀锚定免逐段探查）。
  优先 `from fill_skill import fill_blank, fill_cell, replace_in_para, insert_picture_after` 使用；
  下划线空白一律用 fill_blank（值填*在线上*，不会附加到下划线之后）
- **取值优先级**：项目名称/编号等取 facts.yaml 的 template_fields；企业名称/法人/信用代码取
  facts.yaml 的 company_name/legal_person/credit_code；其余资质/案例/人员/业绩只引用 kb.md 实有内容
- 图片处理：需要插图（营业执照/资质证书/业绩佐证等）时用 insert_picture_after **实际插入**，不要只写路径；仍**禁止读取/查看图片内容**（会超出消息缓冲），依据文件名判断是否需要插入
- 格式保持：填写时**不得删除/隐藏模板中的下划线（＿＿＿）、表格线、签字/盖章占位**等原有格式元素，保持模板原格式
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.format(output=output)
