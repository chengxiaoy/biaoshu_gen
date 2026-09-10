"""企业信息本地记账：确定性信息不走检索，直接整册读取（设计文档「标书智能体知识库构建」）。

设计文档把标书用到的信息分两类：
- 企业信息（企业/法人/资质证书）：确定性信息，不需要 RAG 筛选，直接确定性使用
  ——本模块把它们按目录整册记账（提文本 + 登记图片路径）；
- 产品信息（产品文档/手册）：交给 kb_v2 在 RAGFlow 建知识库，检索与 Agentic RAG
  只作用于这一部分。

分流规则：kb_dir 下**顶层目录名含「企业信息」**的整个子树归记账区；其余目录的
文档归 kb_v2。图片是插图素材（fill 插图 / harness 查看），无论在哪个区都登记进
images 清单（本地磁盘路径），产品图片同时上传 kb_v2 走 OCR 检索。
"""
from dataclasses import dataclass, field
from pathlib import Path

from .docx_io import docx_to_markdown
from .utils import pdf_to_markdown

LEDGER_KEYWORD = "企业信息"          # 顶层目录名含此关键词 -> 记账区
_TEXT_EXTS = {".txt", ".md"}
_DOCX_EXTS = {".docx"}
_DOC_EXTS = _TEXT_EXTS | _DOCX_EXTS | {".pdf"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
# kb_v2 可上传口径（与 kb_v2._UPLOAD_EXTS 一致；含图片——产品图走 OCR 检索）
_RAGFLOW_EXTS = {".txt", ".md", ".docx", ".pdf", ".pptx"} | _IMAGE_EXTS


@dataclass
class CompanyLedger:
    """企业信息记账本：确定性文本 + 插图素材路径（本地磁盘，不经检索）。"""

    texts: list[tuple[str, str]] = field(default_factory=list)   # (来源文档名, 全文)
    images: list[Path] = field(default_factory=list)             # 全部图片（跨区，插图素材）

    def dump(self, path: Path) -> Path:
        """写成 harness 可读的记账 Markdown（原 kb.dump_summary 的职责继承）。"""
        parts = ["# 企业信息记账（确定性信息，禁止改写数值与名称）\n"]
        for name, text in self.texts:
            parts.append(f"## 来源：{name}\n\n{text}\n")
        if self.images:
            parts.append("## 图片材料（可直接查看的绝对路径）")
            parts.extend(f"- {p.resolve()}" for p in self.images)
        path.write_text("\n".join(parts), encoding="utf-8")
        return path


def _is_ledger_dir(p: Path, root: Path) -> bool:
    """顶层目录名含「企业信息」即记账区；根下散文件不属任何企业信息子目录 -> 产品区。"""
    try:
        top = p.relative_to(root).parts[0]
    except (IndexError, ValueError):
        return False
    return LEDGER_KEYWORD in top


def build(kb_dir: Path) -> CompanyLedger:
    """扫描 kb_dir 生成企业信息记账本（确定性读取，不走任何检索）。"""
    root = Path(kb_dir)
    ledger = CompanyLedger()
    if not root.exists():
        return ledger
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        ext = p.suffix.lower()
        if ext in _IMAGE_EXTS:
            ledger.images.append(p)                    # 图片跨区登记：插图素材
            continue
        if not _is_ledger_dir(p, root) or ext not in _DOC_EXTS:
            continue
        try:
            if ext in _TEXT_EXTS:
                text = p.read_text(encoding="utf-8")
            elif ext in _DOCX_EXTS:
                text = docx_to_markdown(p)
            else:
                text = pdf_to_markdown(p)
        except Exception:                              # 坏文件跳过，不拖垮整本账
            continue
        if text.strip():
            ledger.texts.append((p.name, text))
    return ledger


def ragflow_files(kb_dir: Path) -> list[Path]:
    """应交给 kb_v2 上传的文件：非记账区的可解析文档（产品资料文档 + 产品图片）。"""
    root = Path(kb_dir)
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and not p.name.startswith(".")
        and not _is_ledger_dir(p, root) and p.suffix.lower() in _RAGFLOW_EXTS
    )


def has_images(kb_dir: Path) -> bool:
    """kb 里是否存在图片（后缀短路探测，不解析文档）。

    fill_forms 的插图 pass 触发只需这个布尔——用 build() 全量记账会顺带把每个
    docx/pdf 做文本提取（一次 fill 最多调 4 次 build，附加段并行再翻倍），
    对一个 yes/no 问题纯属浪费；图片集在 run 生命周期内不变，后缀探测足够。
    """
    root = Path(kb_dir)
    if not root.exists():
        return False
    return any(p.suffix.lower() in _IMAGE_EXTS
               for p in root.rglob("*") if p.is_file())
