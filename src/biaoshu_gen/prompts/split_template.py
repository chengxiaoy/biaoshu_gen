"""模板三分拆 prompt(仅无标题模板的 LLM 兜底路径使用)。"""

SYSTEM = "你是投标文件结构分析师，负责把无标题样式的响应模板按内容归属分段。"

TEMPLATE = """以下是一份响应文件模板的编号内容块(无标题样式,表格压成【表格】行):

{blocks_text}

任务:把相邻的内容块归入三个部分之一,输出 spans 列表,每个元素含:
- start_index / end_index:块序号区间(end 含本身;最后一个区间 end_index 用 null 表示到末尾)
- bucket:三个取值之一
  - deviation:偏离表部分(合同条款/采购需求/技术等偏离表)
  - technical:技术/实施方案部分(项目实施方案、技术方案)
  - forms:其余填写部分(投标函/响应声明/报价/价格表/一览表/资格证明/保证金/政策优惠/业绩等,catch-all)

规则:
- 只分**大的功能段**,不要逐块输出;同一 bucket 的多个相邻段合并为一个 span
- spans 之外的块默认归 forms,不确定归属时留给 forms
- 区间按文档顺序排列,不重叠
- 只通过结构化输出返回结果,不要输出其他内容
"""


def build_user_prompt(blocks_text: str) -> str:
    return TEMPLATE.replace("{blocks_text}", blocks_text)
