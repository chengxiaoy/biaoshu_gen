"""偏离表填写 prompt（非 harness）：LLM 按发现的表动态直出数据行，python 回写整表。"""

SYSTEM = "你是投标文件填写专员，负责按响应模板偏离表的列结构逐行生成填写内容。"

TEMPLATE = """响应模板中发现以下偏离表（已转 markdown，首行为表头；表序号用于回写匹配）：

{table_sections}

【标书需求 requirements.yaml】
{requirements}

【废标项与扣分项 invalidation.yaml】
{invalidation}

【全局事实设定 facts.yaml（应答必须与此一致）】
{facts}

任务：为上述每张偏离表生成全部数据行，结构化输出 tables 列表，每个元素含
table_index（表序号，与上方标注一致）与 rows。每行字段：
- clause：磋商/招标文件章节条款号
- requirement：招标要求（摘录原文要点）
- response：响应文件的应答
- deviation：偏离说明

规则：
- requirements.yaml 的技术要求、实施要求与商务参数逐条入表；invalidation.yaml 中被扣分评分的条目必须逐条入表
- 每张表按其标题与「填写指引」选相应类别的要求，不要把同一要求重复填进多张表
- 应答与 facts.yaml 承诺一致（交货日期/质保期等）；严禁任何负偏离；无偏离时 deviation 写「无偏离」
- 某张表确实无对应要求时其 rows 可为空，但至少一张表非空
- 每行 requirement 与 response 必须非空；所有表总行数不超过 200
- 只通过结构化输出返回结果，不要输出其他内容
"""


def fill_guidance(caption: str) -> str:
    """按表标题语义给单张偏离表的填写指引（支持合同条款/技术/商务/采购需求等形态）。"""
    if "合同" in caption:
        return "填写合同草案条款类偏离（交货期/质保期/付款/违约等）"
    if "技术" in caption:
        return "填写技术参数与技术要求类偏离"
    if "商务" in caption:
        return "填写商务条款类偏离"
    return "按表标题语义填写相应类别要求的偏离"


def build_table_section(index: int, caption: str, table_md: str) -> str:
    return (f"【表{index}：{caption or '（无标题偏离表）'}】{fill_guidance(caption)}\n{table_md}")


def build_user_prompt(table_sections: list[str], requirements: str,
                      invalidation: str, facts: str) -> str:
    # 用 replace 而非 format：正文无花括号，但保持与其它 prompt 一致的安全渲染方式
    return (TEMPLATE
            .replace("{table_sections}", "\n\n".join(table_sections))
            .replace("{requirements}", requirements)
            .replace("{invalidation}", invalidation)
            .replace("{facts}", facts))
