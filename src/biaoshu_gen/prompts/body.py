"""技术方案正文生成节点 prompt。"""

SYSTEM = "你是资深软件投标技术方案撰写人。严格依据全局事实设定写作，禁止与事实冲突的承诺。"

TEMPLATE = """撰写技术方案的一个章节正文。

【章节】{title}
【目标字数】约 {target_words} 字（非空白字符计，允许 ±20% 偏差）
【本章要点】{key_points}

【全局事实设定（必须严格遵守）】
{facts}

【企业知识库参考材料】
{kb}

{feedback}写作要求：
- 输出 Markdown 正文（可用 ##/### 子标题与列表），不要以章标题开头
- 覆盖全部要点，呼应招标技术要求与技术评分标准
- 引用企业案例/资质时只能使用参考材料中出现的信息
"""


def build_user_prompt(title: str, target_words: int, key_points: list[str],
                      facts: str, kb: str, feedback: str = "") -> str:
    fb = f"【上一轮审核意见（必须修复）】\n{feedback}\n\n" if feedback else ""
    return TEMPLATE.format(
        title=title, target_words=target_words,
        key_points="；".join(key_points) or "（无）",
        facts=facts or "（无）", kb=kb or "（无）", feedback=fb,
    )
