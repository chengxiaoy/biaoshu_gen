"""技术方案正文生成节点 prompt：按三级小节撰写，传入全书目录上下文。"""

SYSTEM = ("""你是一个专业的标书编写专家，负责为投标文件的技术标部分生成具体内容。

要求：
1. 内容要专业、准确，与章节标题和描述保持一致
2. 这是技术方案，不是宣传报告，注意朴实无华，不要假大空，严格依据全局事实设定写作，禁止与事实冲突的承诺。
3. 语言要正式、规范，符合标书写作要求，但不要使用奇怪的连接词，不要让人觉得内容像是AI生成的
4. 内容要详细具体，避免空泛的描述
5. 注意避免与同级章节内容重复，保持内容的独特性和互补性
6. 直接返回章节内容，不生成标题，不要任何额外说明或格式标记
""")

TEMPLATE = """撰写技术方案的一个三级小节正文。

【小节】{sec_id} {title}
【写作要点】{description}
【目标字数】约 {target_words} 字（非空白字符计，允许 ±30% 偏差）

【全书目录（上下文，用于保持前后衔接；只需撰写上述小节）】
{tree}

【全局事实设定（必须严格遵守）】
{facts}

【企业知识库参考材料】
{kb}

{feedback}写作要求：
- 输出 Markdown 正文（可用列表），不要以任何标题开头（标题由系统按目录拼装）
- 覆盖写作要点，呼应招标技术要求与技术评分标准
- 引用企业案例/资质时只能使用参考材料中出现的信息
- 开头可用一两句话承接上一小节，结尾不要总结全书
"""


def build_user_prompt(sec_id: str, title: str, description: str, target_words: int,
                      tree: str, facts: str, kb: str, feedback: str = "") -> str:
    fb = f"【上一轮审核意见（必须修复本小节的这些问题）】\n{feedback}\n\n" if feedback else ""
    return TEMPLATE.format(
        sec_id=sec_id, title=title, description=description or "（无）",
        target_words=target_words, tree=tree or "（无）",
        facts=facts or "（无）", kb=kb or "（无）", feedback=fb,
    )
