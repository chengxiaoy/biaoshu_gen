"""按审核意见修改草稿 prompt（harness）。"""

SYSTEM = "你是投标文件修订专员，按审核意见批量修改标书草稿。"

TEMPLATE = """工作区文件：
- {current}：当前标书草稿 docx（待修改）
- review_report.md：审核意见（问题清单，以此为准逐条修订）

facts/invalidation/scoring 已附于本 prompt 末尾；草稿结构用步骤 1 的 dump_fill_points 一次获取，
**不要逐个 Read 探查**；确需核对再读一次对应文件。

任务：按审核意见逐条修改草稿，产出新版本 {output}。

**执行方式（一次脚本批量改，禁止一处一处小改）**：
1. 先用一条命令拿草稿地图：python -c "import docx; from fill_skill import dump_fill_points; print(dump_fill_points(docx.Document('{current}')))"
   （工作区已提供 fill_skill.py：fill_blank/fill_cell/replace_in_para/insert_picture_after，下划线填空值在线上）
2. 基于地图与审核意见，把**全部**修改写进**一个** python-docx 驱动脚本（按顺序列出每处改动的 段落/run/单元格 与目标文本，含替换占位、填日期、补序号等），一次运行
3. 脚本报错或产物有误时，集中修正报错处重跑（通常一次收敛），不要逐条试错
4. 用 python-docx 读取当前草稿、修改后另存为新文件（禁止覆盖原文件）；若正文变化同步产出 {md_output}

要求：
- 只修复意见指出的问题，保留既有正确内容；修改不得违反 facts.yaml、不得触犯废标项
- 不得删减或调整 标书模板.docx 中的结构或章节；技术方案正文标题格式须与模板整体标题结构衔接一致
- 完成后 {output} 必须存在且非空。"""


def build_user_prompt(output: str, version: int, current: str = "") -> str:
    current = current or f"标书草稿_v{max(version - 1, 1)}.docx"
    md_output = output.replace(".docx", ".md")
    return TEMPLATE.format(current=current, output=output, md_output=md_output)
