"""其余填写部分整体填写 prompt（原 forms+commercial 合并，feedback #78）。

程序化路径：LLM 直出填写 plan（FillOp 列表），python 经 fill_skill.run_fill_plan
确定性执行；plan 失败/执行报错时由 harness 兜底（build_fallback_prompt），
让 agent 在既有产物副本上直接补填。"""

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
- {{"op":"picture","prefix":"备注：","img":"<预注入的图片绝对路径>","width":4.8,"caption":"附：营业执照"}}  # 实际插图
- {{"op":"append","prefix":"投标人名称：","value":"…"}}                  # 无标签锚时的段末追加

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
- 资格证明文件：按模板小节填入企业资料与预注入的企业信息摘要中的资质，并实际插入相应图片（picture op，禁止读取图片内容）
- 商务响应内容（业绩证明/拟派项目团队/保证金/政策优惠等其他商务文件小节）：
  逐条响应预注入的评分标准（scoring）中的商务项；资质/案例/人员/业绩**只能引用
  预注入的企业信息摘要中实际存在的内容**，摘要中没有的**不发 op**（缺失空位留给人工补，禁止编造、禁止占位值）

填写规则：
- 企业资料若为 mock 占位值（含「待替换」），照填并在 plan 后无从标注--保持原值即可
- 只操作模板既有段落/表格（prefix 与 table_header 取自预注入的模板可填点地图），不新建结构
- **严格依据事实填写，不得编造**：所有承诺必须与 facts 一致
- 图片用预注入的绝对路径**实际插入**（picture op）；禁止读取/查看图片内容
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


FALLBACK_SYSTEM = (
    "你是投标文件填写专员。程序化填写（LLM 出 plan + python 确定性执行）已完成，"
    "遗留空位由你在既有产物副本上直接写脚本补填。"
)

FALLBACK_TEMPLATE = """工作区文件：
- {output}：**你的工作对象**——程序化填写后的产物副本（预填+已执行的 op 都在其中），
  打开它补填，补完保存回原路径
- 标书模板.docx：原始模板切片（对照参考，不要改动它）
- tender.md：招标文件全文；scoring.yaml：评分标准（含商务评分）
- facts.yaml：全局事实设定；metadata.yaml：项目参数；kb.md：企业知识库全文（资质/案例明细）
- fill_skill.py：填写原语（表格/下划线填空/插图），直接 import 使用

任务：{task_desc}

执行流程（材料已预注入本 prompt 末尾，禁止逐文件探查；kb.md 仅在需核对资质明细时读一次）：
1. 基于 prompt 末尾的【模板可填点地图】与【facts/metadata/图片路径】，写**一个**驱动脚本：
   from fill_skill import run_fill_plan
   PLAN = [
     {"op": "label", "label": "项目名称：", "value": "……"},
     {"op": "table", "table_header": ["序号", "项目名称"], "rows": [["1", "……"]]},
     {"op": "cell", "table_header": ["序号", "项目名称"], "row": 1, "col": 1, "value": "……"},
     {"op": "append", "prefix": "业绩证明文件", "value": "……"},
     {"op": "picture", "prefix": "其他商务文件", "img": "<预注入的图片绝对路径>", "width": 4.8, "caption": "附：资质证书"},
   ]
   errors = run_fill_plan('{output}', '{output}', PLAN)
   print(errors or 'OK')
2. errors 非空时只修正报错条目重跑

要求：
- **严格依据事实填写，不得编造**：承诺与 facts.yaml 一致；资质/案例/人员/业绩只引用
  kb.md 实有内容，缺失**不发 op**（占位值会被丢弃，空位留给人工）
- 图片用预注入的绝对路径**实际插入**（picture op）；禁止读取/查看图片内容
- 格式保持：不得删除/隐藏下划线、表格线、签字/盖章占位；只操作既有段落/表格，不新建结构
"""


def build_fallback_prompt(output: str, errors: list[str], plan_failed: bool) -> str:
    """harness 兜底 prompt：plan_failed=全量填写（程序化通道没产出 plan）；
    否则只补【报错清单】列出的空位。"""
    if plan_failed:
        task = (f"程序化填写通道未能产出合法 plan（预填已完成），请对 {output} 做**全量**"
                "填写（范围：投标函/报价/一览表/资格证明/商务响应，按下方要求）")
    else:
        task = ("程序化填写的以下操作执行报错，请只补填这些空位（其余内容已填好，"
                "不要重复填写、不要改动未列出部分）：\n"
                + "\n".join(f"- {e}" for e in errors[:30]))
    return FALLBACK_TEMPLATE.replace("{output}", output).replace("{task_desc}", task)
