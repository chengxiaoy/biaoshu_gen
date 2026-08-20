"""按审核意见修改草稿 prompt（harness）。"""

SYSTEM = "你是投标文件修订专员，按审核意见批量修改标书草稿。"

TEMPLATE = """{env}

工作区文件：
- {current}：当前标书草稿 docx（待修改）
- review_report.md：审核意见（以此为准逐条修订；其中事实与数字已核对过，直接采信，不要重新 grep tender.md 验证）
- _map.txt：草稿结构地图（全部段落 [下标] 前缀 + 各表格内容清单，宿主已生成）

facts/invalidation/scoring 已附于本 prompt 末尾。

任务：按审核意见逐条修改草稿，产出新版本 {output}。

**执行方式（一次脚本批量改，禁止一处一处小改）**：
1. 定位修改目标：优先 `grep -n "关键词" _map.txt` 或局部 Read 对应区间；**不要整文件通读，也不要自己重新 dump 地图**
2. 把**全部**修改写进**一个** python-docx 驱动脚本（按顺序列出每处改动的 段落/run/单元格 与目标文本，含替换占位、填日期、补序号等），一次运行
   （工作区已提供 fill_skill.py：fill_blank/fill_cell/replace_in_para/insert_picture_after，下划线填空值在线上）
3. 脚本报错或产物有误时，集中修正报错处重跑（通常一次收敛），不要逐条试错
4. 修改后另存为新文件（禁止覆盖原文件）；若正文变化同步产出 {md_output}

要求：
- 只修复意见指出的问题，保留既有正确内容；修改不得违反 facts.yaml、不得触犯废标项
- 不得删减或调整 标书模板.docx 中的结构或章节；技术方案正文标题格式须与模板整体标题结构衔接一致
- 完成后 {output} 必须存在且非空。"""


def build_user_prompt(output: str, version: int, current: str = "", env: str = "") -> str:
    current = current or f"标书草稿_v{max(version - 1, 1)}.docx"
    md_output = output.replace(".docx", ".md")
    return TEMPLATE.format(env=env, current=current, output=output, md_output=md_output).lstrip("\n")
