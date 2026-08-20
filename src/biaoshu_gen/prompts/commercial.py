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

执行流程（**材料已预注入本 prompt 末尾，禁止再读任何文件探查**；kb.md 仅在需核对资质明细时读一次）：
1. 基于 prompt 末尾的【模板可填点地图】与【facts/metadata/图片路径】，直接写**一个**驱动脚本：
   from fill_skill import run_fill_plan
   PLAN = [
     {"op": "cell", "table_header": ["序号", "项目名称"], "row": 1, "col": 1, "value": "……"},
     {"op": "append", "prefix": "业绩证明文件", "value": "……"},      # 小节下插信息文字
     {"op": "picture", "prefix": "其他商务文件", "img": "<预注入的图片绝对路径>", "width": 4.8, "caption": "附：资质证书"},
   ]
   errors = run_fill_plan('标书模板.docx', '{output}', PLAN)
   print(errors or 'OK')
2. errors 非空时只修正报错条目重跑；产物为 {output}

要求：
- **严格依据事实填写，不得编造**：承诺与 facts.yaml 一致；资质/案例/人员/业绩只引用 kb.md 实有内容，
  缺失留空或注〔待补〕
- 图片用 kb.md 绝对路径**实际插入**（picture op）；禁止读取/查看图片内容
- 格式保持：不得删除/隐藏下划线、表格线、签字/盖章占位
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.replace("{output}", output)  # 花括号安全
