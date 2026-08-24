"""标书草稿全面审核 prompt（PydanticAI 单次调用，非 harness）。

输入为节点预注入的草稿全文 + 依据材料；输出结构化 ReviewReport。
"""

SYSTEM = "你是投标文件审核专家，对标书草稿做全面审核并给出结构化结论。"

TEMPLATE = """对以下标书草稿做全面审核，输出结构化结论。

【标书草稿全文（Markdown 化）】
{draft}

【全局事实设定（facts.yaml 全文）】
{facts}

【废标项+扣分项（invalidation.yaml 全文，逐条核对是否触犯/响应）】
{invalidation}

【评分标准（scoring.yaml 全文，核对扣分项是否逐条响应）】
{scoring}

【响应文件模板结构（template.md 的目录树与填写要求）】
{template}

按以下六方面逐项审核，每方面给出 passed（通过/不通过）与 note（具体说明）：
1. 废标项+扣分项：草稿是否触犯废标项；扣分项是否均已响应（报价未填属待办，不算触犯但须在 note 标注）
2. 事实一致性：草稿承诺与 facts.yaml 是否一致（工期/人员/软件指标）
3. 必要引用项：偏离表、废标项、扣分项相关引用是否齐全
4. 材料齐全性：只判断响应文件模板要求的**结构性组成部分**是否都在草稿中；因缺具体数据/证件/证明内容导致的空缺不算本方面不通过
5. 格式问题：是否符合模板结构与格式要求（签字/盖章/附件）
6. 模板结构融合：技术方案正文标题格式是否与模板整体标题结构衔接一致；模板结构/章节是否被删减或调整

问题分类（务必区分，数据缺失不是草稿缺陷）：
- issues：仅收**可修复的草稿缺陷**——格式错误、内容矛盾、结构或表述不一致、应响应未响应等，每条注明涉及的方面
- human_todos：**数据缺失类**——缺身份证号/联系方式/落款名称/签章日期/业绩证明材料等需人工补全的信息。只写入 human_todos，
  **不得**写入 issues，**不得**导致任何方面 passed=false

总结论 passed：仅由 issues 驱动，issues 为空即 passed=true。
human_todos：无数据缺失时为空列表。"""


def build_user_prompt(*, draft: str, facts: str, invalidation: str,
                      scoring: str, template: str) -> str:
    return TEMPLATE.format(
        draft=draft or "（无）",
        facts=facts or "（无）",
        invalidation=invalidation or "（无）",
        scoring=scoring or "（无）",
        template=template or "（无）",
    )
