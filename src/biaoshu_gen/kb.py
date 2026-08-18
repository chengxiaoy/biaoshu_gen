"""企业信息知识库：本地目录加载 + jieba/BM25 关键词检索（POC 不做向量 RAG）。"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi

from .docx_io import docx_to_markdown

_TEXT_EXTS = {".txt", ".md"}
_DOCX_EXTS = {".docx"}
_CHUNK_SIZE = 800


@dataclass
class KbChunk:
    source: Path
    text: str


@dataclass
class KnowledgeBase:
    chunks: list[KbChunk] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    images: list[Path] = field(default_factory=list)

    @classmethod
    def load(cls, dir: Path) -> "KnowledgeBase":
        kb = cls()
        if not dir.exists():
            return kb
        for p in sorted(dir.rglob("*")):
            if not p.is_file() or p.name.startswith("."):
                continue
            kb.files.append(p)
            if p.suffix.lower() in _TEXT_EXTS:
                kb._add_text(p, p.read_text(encoding="utf-8"))
            elif p.suffix.lower() in _DOCX_EXTS:
                kb._add_text(p, docx_to_markdown(p))
            elif p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                kb.images.append(p)
        return kb

    def _add_text(self, source: Path, text: str) -> None:
        buf: list[str] = []
        size = 0
        for para in re.split(r"\n\s*\n", text):
            buf.append(para)
            size += len(para)
            if size >= _CHUNK_SIZE:
                self.chunks.append(KbChunk(source, "\n".join(buf).strip()))
                buf, size = [], 0
        if buf:
            self.chunks.append(KbChunk(source, "\n".join(buf).strip()))

    def search(self, query: str, top_k: int | None = None) -> list[KbChunk]:
        if not self.chunks:
            return []
        from .config import get_settings
        top_k = top_k or get_settings().kb_top_k
        corpus = [[t for t in jieba.lcut(c.text) if t.strip()] for c in self.chunks]
        scores = BM25Okapi(corpus).get_scores([t for t in jieba.lcut(query) if t.strip()])
        ranked = sorted(zip(scores, self.chunks), key=lambda x: x[0], reverse=True)
        return [c for s, c in ranked[:top_k] if s > 0]

    def image_paths(self) -> list[Path]:
        return list(self.images)

    def all_files(self) -> list[Path]:
        return list(self.files)

    def dump_summary(self, path: Path) -> Path:
        """写给 harness 节点读的知识库摘要：文本块 + 图片绝对路径清单。"""
        parts = ["# 企业知识库摘要\n"]
        for c in self.chunks:
            parts.append(f"## 来源：{c.source.name}\n\n{c.text}\n")
        if self.images:
            parts.append("## 图片材料（可直接查看的绝对路径）")
            parts.extend(f"- {p.resolve()}" for p in self.images)
        path.write_text("\n".join(parts), encoding="utf-8")
        return path


def count_chars(text: str) -> int:
    """字数统计口径：非空白字符数（正文字数校验使用）。"""
    return len(re.sub(r"\s", "", text))
