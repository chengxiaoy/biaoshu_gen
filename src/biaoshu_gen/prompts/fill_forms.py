"""其余填写部分整体填写 prompt（原 forms+commercial 合并，feedback #78）。

程序化路径：LLM 直出填写 plan（FillOp 列表），python 经 fill_skill.run_fill_plan
确定性执行；plan 失败/报错记 error.log 供人工补（不弃产物）。fill 阶段 harness 的
唯一任务是插图 pass（build_picture_prompt）：agent 对照产物实况自主决定插图位置。"""

SYSTEM = "你是投标文件填写专员，负责按响应模板的既有格式逐项生成填写操作。"

TEMPLATE = """任务：为响应模板副本生成填写操作序列（结构化输出 plan），系统将用确定性
原语逐条执行并产出 {output}。plan 每条操作的取值：
- {{"op":"label","label":"项目名称：","value":"…"}}   # 按标签填空:标签在段首或段中（如
  「采购代理编号：__ 项目名称：__」同段多空）皆可,填全部命中;有无下划线均可——值落线上
  (留余线)或直接跟在标签后,标签后已是实义文本(已填过)的自动跳过
- {{"op":"table","table_header":["序号","名称","数量"],"rows":[["1","AI算力","1"],["2","数据底座","1"]],"start_row":1}}
  # 同表多格**必须**按行批量填:rows 每个内层 list 是一行,按列顺序对位;null=跳过该格;
  # 行数不足自动加行。只有散落个别格子才用 cell
- {{"op":"cell","table_header":["序号","服务期"],"row":1,"col":1,"value":"…"}}  # 散落单格按表头定位
- {{"op":"replace","prefix":"致：","old":"（采购人名称）","new":"…"}}     # 段内文本替换（括号占位等,全部命中同前缀段落）
- {{"op":"append","prefix":"投标人名称：","value":"…"}}                  # 无标签锚时的段末追加
（不发 picture：图片插入由后续 harness 阶段对照文档实况自主处理）

投标人企业资料（必填项，一律取自预注入的 facts）：
- 企业/投标人名称：{company_name}
- 法定代表人：{legal_person}
- 统一社会信用代码：{credit_code}

填写范围（其余填写部分**整体**，覆盖投标函到商务文件的全部内容）：
- 投标函：按模板格式填写，含项目名称/编号/投标有效期
- 报价数字（报价文件/开标一览表/分项报价表的金额单元格）：**不发 op**，空位保持原样
  （系统会丢弃一切含「〔待人工填写〕」「〔待补〕」等占位值的 op），留给人工填写
- 货物一览表：按预注入的采购清单与 metadata 用 table op 按行批量填入对应表格；
  金额列发 null 跳过
- 资格证明文件：按模板小节填入企业资料与预注入的企业信息摘要中的资质（图片插入由
  后续 harness 阶段负责，本 plan 不发 picture）
- 商务响应内容（业绩证明/拟派项目团队/保证金/政策优惠等其他商务文件小节）：
  逐条响应预注入的评分标准（scoring）中的商务项；资质/案例/人员/业绩**只能引用
  预注入的企业信息摘要中实际存在的内容**，摘要中没有的**不发 op**（缺失空位留给人工补，禁止编造、禁止占位值）

填写规则：
- 企业资料若为 mock 占位值（含「待替换」），照填并在 plan 后无从标注--保持原值即可
- 只操作模板既有段落/表格（prefix 与 table_header 取自预注入的模板可填点地图），不新建结构
- **严格依据事实填写，不得编造**：所有承诺必须与 facts 一致
- 格式保持：不得删除/隐藏模板中的下划线、表格线、签字/盖章占位
- 若上次 plan 执行报错，只修正报错条目，输出修正后的完整 plan
"""


def build_user_prompt(output: str, company_name: str = "", legal_person: str = "",
                      credit_code: str = "") -> str:
    # 用 replace 而非 format：正文含 PLAN 字典花括号，format 会误解析
    return (TEMPLATE
            .replace("{output}", output)
            .replace("{company_name}", company_name or "（facts 缺失）")
            .replace("{legal_person}", legal_person or "（facts 缺失）")
            .replace("{credit_code}", credit_code or "（facts 缺失）"))


# ---- 插图 pass（fill 阶段 harness 的唯一任务，feedback #86 终版）----
# plan 失败/报错 op 不再交 harness 兜底（记 error.log 供人工补），harness 只插图。
PICTURE_SYSTEM = (
    "你是投标文件排版助理，只负责把应附的证照/证明图片插入产物；"
    "不做任何其他填写，不改动正文文字与表格。"
)

PICTURE_TEMPLATE = """工作区文件：
- {output}：**你的工作对象**——程序化填写后的产物，打开它插图，插完保存回原路径
- 标书模板.docx：原始模板切片（对照参考，不要改动它）
- kb.md：企业知识库全文（仅在需核对资质明细时读一次）
- fill_skill.py：填写原语（insert_picture_after），直接 import 使用

任务：为 {output} 插入应附的证照/证明图片（只做这一件事）：
1. 依据 prompt 末尾的【kb 图片绝对路径】清单与产物文档内容（资格证明文件等小节），
   判断哪些图片应插入、插在哪个段落之后
2. 用 fill_skill.insert_picture_after 实际插入（含图注，图宽按版面 3.5~5.2 英寸），
   插完自查每张图的位置与大小
3. 与文档内容无关的图片跳过、不要硬插；禁止读取/查看图片内容
"""


def build_picture_prompt(output: str) -> str:
    # 用 replace 而非 format：与其它 prompt 一致的安全渲染方式
    return PICTURE_TEMPLATE.replace("{output}", output)
