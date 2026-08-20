"""全局事实设定节点 prompt。"""

SYSTEM = "你是投标方案架构师，负责提炼全局事实设定，后续所有正文必须与之一致。"

TEMPLATE = """基于以下招标信息，提炼本次投标的全局事实设定：

【标书元数据】
{metadata}

【评标标准】
{scoring}

【响应模板表格（招标方给定格式中的待填信息）】
{template_md}

输出要求：
- schedule 工期设置：总工期与关键里程碑（必须满足交货日期要求）
- staffing 人员配置：关键角色与人数
- software_metrics 软件指标：对招标技术要求的逐条承诺（优于或等于要求）
- extra 其他全局事实（质保、培训、驻场等承诺）
- company_name/legal_person/credit_code：留空（由系统在填表阶段按需补齐，勿编造）
- template_fields：从上述响应模板表格中提炼填表所需的各类信息并以键值预置——
  如 项目名称/项目编号/采购计划备案号/采购人名称/包号/投标有效期/服务期限 等；
  值取招标文件已知内容，未知留空字符串（填表节点会用到，不得虚构）
"""


def build_user_prompt(metadata: str, scoring: str, template_md: str = "") -> str:
    return TEMPLATE.format(metadata=metadata or "（无）", scoring=scoring or "（无）",
                           template_md=template_md or "（无）")
