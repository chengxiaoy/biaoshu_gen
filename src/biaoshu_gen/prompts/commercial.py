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

执行流程（**严格四步一次成型，禁止逐步探查模板**）：
1. 一条命令拿模板地图（只跑一次）：
   python -c "import docx; from fill_skill import dump_fill_points; print(dump_fill_points(docx.Document('标书模板.docx')))"
2. 读取 facts.yaml / metadata.yaml / kb.md（各自读一次即可）
3. 写**一个**驱动脚本：把商务部分全部填写/插图组织成 PLAN 清单后一次运行——
   from fill_skill import run_fill_plan
   PLAN = [
     {"op": "cell", "table_header": ["序号", "项目名称"], "row": 1, "col": 1, "value": "……"},
     {"op": "append", "prefix": "业绩证明文件", "value": "……"},      # 小节下插信息文字
     {"op": "picture", "prefix": "其他商务文件", "img": "C:/……jpg", "width": 4.8, "caption": "附：资质证书"},
   ]
   errors = run_fill_plan('标书模板.docx', '{output}', PLAN)
   print(errors or 'OK')
4. errors 非空时只修正报错条目重跑；产物为 {output}

要求：
- **严格依据事实填写，不得编造**：承诺与 facts.yaml 一致；资质/案例/人员/业绩只引用 kb.md 实有内容，
  缺失留空或注〔待补〕
- **取值优先级**：项目名称/编号等取 facts.yaml 的 template_fields；企业名称/法人/信用代码取
  facts.yaml 的 company_name/legal_person/credit_code
- 图片用 kb.md 绝对路径**实际插入**（picture op）；禁止读取/查看图片内容
- 格式保持：不得删除/隐藏下划线、表格线、签字/盖章占位
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.replace("{output}", output)  # 花括号安全
