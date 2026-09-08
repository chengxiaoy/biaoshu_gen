"""通用小工具（无业务语义）。"""
import re
from pathlib import Path


def count_chars(text: str) -> int:
    """字数统计口径：非空白字符数（正文字数校验使用）。"""
    return len(re.sub(r"\s", "", text))


def pdf_to_markdown(path: Path) -> str:
    """PDF 文本提取（pypdf；扫描件需先 OCR，本 POC 仅处理文本层 PDF）。"""
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)   # 对坏/缺 xref 容错（扫描件/损坏 PDF 常见）
    parts = []
    for i, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        parts.append(f"## 第 {i} 页\n\n{text}" if text else f"## 第 {i} 页\n\n（无文本层）")
    return "\n\n".join(parts)
