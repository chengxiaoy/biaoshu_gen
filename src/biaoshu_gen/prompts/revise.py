"""按审核意见修改草稿 prompt（harness）。"""

SYSTEM = "你是投标文件修订专员，按审核意见最小化修改标书草稿。"

TEMPLATE = """工作区文件：
- {current}：当前标书草稿 docx
- review_report.md：审核意见（五方面问题清单）
- tender.md / invalidation.yaml / facts.yaml / kb.md / 标书模板.docx：依据材料

任务：按审核意见逐条修改草稿，产出新版本 {output}：
- 只修复意见指出的问题，保留既有正确内容
- 修改不得违反 facts.yaml，不得触犯废标项
- 不得删减或调整 标书模板.docx 中的结构或章节；技术方案正文标题格式须与模板整体标题结构衔接一致
- 用 python-docx 读取当前草稿、修改后另存为新文件（禁止覆盖原文件）
- 若正文内容变化，同步产出 {md_output}（Markdown 摘要，可选）

完成后 {output} 必须存在且非空。
"""


def build_user_prompt(output: str, version: int, current: str = "") -> str:
    current = current or f"标书草稿_v{max(version - 1, 1)}.docx"
    md_output = output.replace(".docx", ".md")
    return TEMPLATE.format(current=current, output=output, md_output=md_output)
