"""全局事实设定节点 prompt。"""

SYSTEM = "你是投标方案架构师，负责提炼全局事实设定，后续所有正文必须与之一致。"

TEMPLATE = """基于以下招标信息，提炼本次投标的全局事实设定：

【标书元数据】
{metadata}

【评标标准】
{scoring}

输出要求：
- schedule 工期设置：总工期与关键里程碑（必须满足交货日期要求）
- staffing 人员配置：关键角色与人数
- software_metrics 软件指标：对招标技术要求的逐条承诺（优于或等于要求）
- extra 其他全局事实（质保、培训、驻场等承诺）
"""


def build_user_prompt(metadata: str, scoring: str) -> str:
    return TEMPLATE.format(metadata=metadata or "（无）", scoring=scoring or "（无）")
