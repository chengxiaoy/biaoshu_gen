"""Agent 全面审核 prompt（harness）。"""

SYSTEM = "你是投标文件审核专家，对标书草稿做全面审核并给出结论。"

TEMPLATE = """工作区文件：
- 标书草稿.docx / 标书草稿.md：待审草稿（docx 为准，md 为正文摘要）
- tender.md：招标文件全文；invalidation.yaml：废标项+扣分项；scoring.yaml：评分标准
- facts.yaml：全局事实设定；kb.md：企业知识库摘要；标书模板.docx：响应模板（若有）

按以下五方面逐项审核，写出报告 {output}（Markdown）：
1. 废标项+扣分项：草稿是否触犯废标项；扣分项是否均已响应
2. 事实一致性：草稿承诺与 facts.yaml 是否一致（工期/人员/软件指标）
3. 必要引用项：偏离表、废标项、扣分项相关引用是否齐全
4. 材料齐全性：响应文件模板要求的组成部分是否都在草稿中
5. 格式问题：是否符合模板结构与格式要求（签字/盖章/附件）

每个方面给出【通过/不通过】与具体说明。报告最后必须单独一行：
VERDICT: PASS   或   VERDICT: FAIL
- 【重要】kb.md 中列出的图片材料（营业执照等）只需在文档中引用其文件名/路径，禁止用工具查看或读取图片文件（会超出消息缓冲导致任务崩溃）

"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.format(output=output)
