"""商务响应文件填写 prompt（harness）。"""

SYSTEM = "你是投标文件填写专员，负责编制商务响应文件。"

TEMPLATE = """工作区文件：
- tender.md：招标文件全文；scoring.yaml：评分标准（含商务评分）
- facts.yaml：全局事实设定；metadata.yaml：商务参数；kb.md：企业知识库摘要（资质/案例）
- invalidation.yaml：废标项+扣分项

任务：用 python-docx 创建商务响应文件 {output}：
- 逐条响应商务评分标准与商务参数（交货日期、质保期、付款方式、培训等）
- 所有承诺必须与 facts.yaml 一致，不得超出
- 引用 kb.md 中的企业资质/案例作为佐证
- 满足 invalidation.yaml 中关于格式/签字/盖章的要求

完成后文件必须存在且非空。
- 【重要】kb.md 中列出的图片材料（营业执照等）只需在文档中引用其文件名/路径，禁止用工具查看或读取图片文件（会超出消息缓冲导致任务崩溃）

"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.format(output=output)
