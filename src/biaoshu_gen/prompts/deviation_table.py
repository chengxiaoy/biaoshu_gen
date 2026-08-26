"""偏离表填写 prompt（非 harness）：LLM 直出两类偏离表的数据行，python 回写整表。"""

SYSTEM = "你是投标文件填写专员，负责按响应模板偏离表的列结构逐行生成填写内容。"

TEMPLATE = """响应模板中有以下偏离表（已转 markdown，首行为表头）：

【合同条款偏离表】
{contract_md}

【采购需求偏离表】
{requirement_md}

【标书需求 requirements.yaml】
{requirements}

【废标项与扣分项 invalidation.yaml】
{invalidation}

【全局事实设定 facts.yaml（应答必须与此一致）】
{facts}

任务：生成两张偏离表的全部数据行，结构化输出 contract_rows（合同条款偏离表）与
requirement_rows（采购需求偏离表）。每行字段：
- clause：磋商文件章节条款号
- requirement：磋商文件要求（摘录原文要点）
- response：响应文件的应答
- deviation：偏离说明

规则：
- requirements.yaml 的技术要求、实施要求与商务参数逐条入表；invalidation.yaml 中被扣分评分的条目必须逐条入表
- 合同草案条款类（交货/质保/付款/违约等）进 contract_rows；货物/技术/服务参数类进 requirement_rows
- 应答与 facts.yaml 承诺一致（交货日期/质保期等）；严禁任何负偏离；无偏离时 deviation 写「无偏离」
- 模板中不存在的类别（上方标注"无此表"）对应数组留空；两个数组不能同时为空
- 每行 requirement 与 response 必须非空；总行数不超过 200
- 只通过结构化输出返回结果，不要输出其他内容
"""


def build_user_prompt(contract_md: str, requirement_md: str, requirements: str,
                      invalidation: str, facts: str) -> str:
    # 用 replace 而非 format：正文无花括号，但保持与其它 prompt 一致的安全渲染方式
    return (TEMPLATE
            .replace("{contract_md}", contract_md)
            .replace("{requirement_md}", requirement_md)
            .replace("{requirements}", requirements)
            .replace("{invalidation}", invalidation)
            .replace("{facts}", facts))
