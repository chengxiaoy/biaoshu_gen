"""招标文件解析节点 prompt：目录分类 + 分组抽取（分节阅读，避免整篇长上下文）。"""

SYSTEM_CLASSIFY = "你是招标文件结构分析员。只依据给出的目录（章节标题）判断每章属于哪些信息组。"

CLASSIFY_TEMPLATE = """以下是招标文件的目录（章节标题，含序号）：

{toc_lines}

信息组定义：
- metadata：项目名称/编号、投标截止、交货日期、质保期等商务元数据（常见于招标公告/邀请书/投标人须知）
- requirements：采购清单、项目概况、技术要求、实施要求（常见于需求书/技术规范/采购内容章节）
- invalidation：废标项、无效投标、扣分项、偏离要求（常见于评标办法/无效投标条款/废标条款）
- scoring：价格/商务/技术评分标准（常见于评标办法/评分细则）
- 都不属于 -> categories 返回空列表

每个章节输出一个 TocAssignment（index 与目录序号一致）；一个章节可同时属于多组。"""


def build_classify_prompt(toc_lines: list[str]) -> str:
    return CLASSIFY_TEMPLATE.format(toc_lines="\n".join(toc_lines))


SYSTEM_EXTRACT = "你是资深软件投标分析师。只依据给出的章节内容抽取信息，原文没有的留空/空列表，不得臆造。"

EXTRACT_TEMPLATE = """从以下招标文件章节内容中抽取「{group_desc}」：

{sections_text}

要求：
- 只依据原文，不得臆造
- 若本批次无相关信息：字符串字段留空、列表字段返回空列表
- 废标项/扣分项需给出原文依据（source_quote）"""


def build_extract_prompt(group_desc: str, sections_text: str) -> str:
    return EXTRACT_TEMPLATE.format(group_desc=group_desc, sections_text=sections_text)
