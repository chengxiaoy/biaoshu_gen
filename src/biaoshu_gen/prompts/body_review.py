"""正文审核检验节点 prompt。"""

SYSTEM = "你是投标文件审核专家，负责技术方案正文的一致性与合规性检验。"

TEMPLATE = """审核以下技术方案正文。

【全局事实设定】
{facts}

【废标项+扣分项（正文必须响应且不得触犯）】
{invalidation}

【各三级小节字数统计（代码已统计，容差 ±20%，超差已由代码标记）】
{word_table}

检查内容：
1. 与全局事实设定的一致性（工期/人员/指标承诺是否一致）
2. 事实性偏差（是否出现与招标需求矛盾的内容）
3. 废标项与扣分项是否已响应

输出要求：
- issues：问题清单（每条注明涉及的小节 id）
- problem_sections：存在问题的三级小节 id 列表（如 ["1.1.2", "3.2.1"]）——回环时只重写这些小节，务必准确圈定，不要把无问题的小节列进去

正文内容：

{body}
"""


def build_user_prompt(facts: str, invalidation: str, word_table: str, body: str) -> str:
    return TEMPLATE.format(facts=facts or "（无）", invalidation=invalidation or "（无）",
                           word_table=word_table, body=body)
