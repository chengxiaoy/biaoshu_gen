# 软件标书智能体 POC 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按已获批设计文档（`docs/superpowers/specs/2026-08-18-biaoshu-agent-poc-design.md`）搭建端到端可跑通的标书智能体 POC：单一 LangGraph 状态图 + 分阶段 CLI，输入招标文件与企业知识库，产出标书草稿 docx。

**Architecture:** 一张 StateGraph 顺序编排 12 个节点（PydanticAI/DeepSeek 结构化输出节点 + Claude Code SDK harness 节点），SqliteSaver checkpoint 支撑分阶段断点续跑；企业知识库为本地目录 + jieba/BM25 检索；所有中间产物落盘为 YAML/Markdown/docx，两个人工控制点（facts/outline）用户编辑优先。

**Tech Stack:** Python 3.11+ / poetry / langgraph / langgraph-checkpoint-sqlite / pydantic-ai（DeepSeek `deepseek-chat`）/ claude-agent-sdk（继承智谱 Anthropic 网关环境）/ typer / python-docx / jieba / rank-bm25 / pyyaml / pytest

## Global Constraints

- Python `>=3.11,<4.0`；包管理只用 poetry；src 布局 `src/biaoshu_gen/`
- 全部文件 IO 用 `pathlib` + UTF-8；路径含中文不假设 ASCII（Windows 环境）
- CLI 入口名 `biaoshu`；数据目录 `data/`（git 忽略）；run 目录 `data/runs/<run_id>/`
- 非 harness 节点输出必须是 Pydantic 模型（PydanticAI `output_type`）；prompt 全中文，每节点一个 prompt 模块（`src/biaoshu_gen/prompts/`）
- 回环上限：`body_review → body` 2 轮、`review → revise` 2 轮；字数容差 ±20%
- 每个任务结束：pytest 全绿 + git commit（commit 信息用 `feat:`/`test:`/`docs:`/`chore:` 前缀，结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`）
- 运行命令统一 `poetry run pytest ...` / `poetry run biaoshu ...`

---

### Task 1: Poetry 工程骨架 + 配置模块

**Files:**
- Create: `pyproject.toml`
- Create: `src/biaoshu_gen/__init__.py`（空）
- Create: `src/biaoshu_gen/config.py`
- Create: `src/biaoshu_gen/cli.py`（空壳）
- Modify: `.gitignore`（追加 `data/`）
- Create: `data/company/.gitkeep`、`data/tender/.gitkeep`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `get_settings() -> Settings`（`lru_cache`），`Settings` 字段见下方代码——后续所有模块经 `from .config import get_settings` 使用

- [ ] **Step 1: 写 pyproject.toml**

```toml
[tool.poetry]
name = "biaoshu-gen"
version = "0.1.0"
description = "软件标书智能体 POC"
authors = ["Your Name <you@example.com>"]
packages = [{ include = "biaoshu_gen", from = "src" }]

[tool.poetry.dependencies]
python = ">=3.11,<4.0"
langgraph = ">=0.4,<0.7"
langgraph-checkpoint-sqlite = ">=2.0,<3.0"
pydantic-ai = ">=1.0,<2.0"
claude-agent-sdk = ">=0.1,<1.0"
typer = ">=0.12,<1.0"
python-docx = ">=1.1,<2.0"
jieba = ">=0.42,<0.43"
rank-bm25 = ">=0.2.2,<0.3"
pyyaml = ">=6.0,<7.0"
pydantic-settings = ">=2.0,<3.0"

[tool.poetry.group.dev.dependencies]
pytest = ">=8.0,<9.0"

[tool.poetry.scripts]
biaoshu = "biaoshu_gen.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

- [ ] **Step 2: 写 `src/biaoshu_gen/config.py` 与空壳 cli**

`config.py`:

```python
"""全局配置：经 .env / 环境变量注入，POC 阶段路径均相对仓库根。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DeepSeek（PydanticAI 非 harness 节点）
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    # harness 节点走 claude-agent-sdk，继承本机 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN，无需配置

    data_dir: Path = Path("data")

    # 流程控制参数（设计文档 §7）
    body_review_max_rounds: int = 2
    revise_max_rounds: int = 2
    word_tolerance: float = 0.2
    harness_max_turns: int = 100
    kb_top_k: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`cli.py` 空壳（后续任务填充命令）:

```python
import typer

app = typer.Typer(help="软件标书智能体 POC", no_args_is_help=True)


def main() -> None:
    app()
```

`.gitignore` 末尾追加：

```
# 运行数据（招标文件/企业库/runs 产物）
data/
```

注意：`data/` 整体忽略后，`.gitkeep` 也不会入库——可接受，README 会说明目录用途；或者改为忽略 `data/runs/` 并保留 `data/*/.gitkeep`。执行时采用后者：忽略 `data/runs/`，`data/company/`、`data/tender/` 留 `.gitkeep`。

- [ ] **Step 3: 写失败测试 `tests/test_config.py`**

```python
from biaoshu_gen.config import Settings


def test_settings_defaults():
    s = Settings()
    assert s.deepseek_model == "deepseek-chat"
    assert s.deepseek_base_url == "https://api.deepseek.com"
    assert s.body_review_max_rounds == 2
    assert s.revise_max_rounds == 2
    assert s.word_tolerance == 0.2
    assert str(s.data_dir) == "data"


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    s = Settings()
    assert s.deepseek_api_key == "sk-test"
```

- [ ] **Step 4: 验证失败后实现、再验证通过**

先 `poetry install`（若本机无 poetry：`pip install poetry` 先装）。运行 `poetry run pytest tests/test_config.py -v`，预期 import 失败 → 上述文件已写则直接通过；若未写 config 则失败。补齐后运行预期 2 passed。

- [ ] **Step 5: 验证 CLI 空壳可用**

Run: `poetry run biaoshu --help`
Expected: 输出帮助文本，退出码 0。

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src tests .gitignore data/tender/.gitkeep data/company/.gitkeep poetry.lock
git commit -m "chore: poetry 工程骨架与全局配置"
```

---

### Task 2: schemas.py —— 全部节点输出模型 + YAML 读写

**Files:**
- Create: `src/biaoshu_gen/schemas.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Produces: `TenderMetadata` / `TenderRequirements` / `InvalidationItem` / `InvalidationItems` / `ScoringStandards` / `GlobalFacts` / `OutlineSection` / `Outline` / `SectionBody` / `BodyReviewReport` / `ParseResult` / `TocAssignment` / `TocMap`（字段见代码，后续节点与测试直接引用）
- Produces: `to_yaml_file(model: BaseModel, path: Path) -> None`、`from_yaml_file(cls: type[T], path: Path) -> T`（校验失败抛 `ValueError`，含字段级信息）

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

import pytest

from biaoshu_gen.schemas import (
    GlobalFacts, InvalidationItem, Outline, OutlineSection, TocMap,
    from_yaml_file, to_yaml_file,
)


def test_invalidation_kind_validation():
    ok = InvalidationItem(kind="扣分项", requirement="质保期不足扣 2 分")
    assert ok.kind == "扣分项"
    with pytest.raises(Exception):
        InvalidationItem(kind="其他", requirement="x")


def test_yaml_roundtrip(tmp_path: Path):
    facts = GlobalFacts(schedule="90 天", staffing="项目经理 1 名",
                        software_metrics=["并发>=1000"], extra=["通过等保三级"])
    p = tmp_path / "03_facts.yaml"
    to_yaml_file(facts, p)
    assert p.read_text(encoding="utf-8").startswith("schedule:")
    assert from_yaml_file(GlobalFacts, p) == facts


def test_from_yaml_file_field_error(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("sections:\n- title: 章节\n  target_words: 五百\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        from_yaml_file(Outline, p)
    assert "target_words" in str(e.value)


def test_outline_defaults():
    o = OutlineSection(title="总体方案")
    assert o.target_words == 500 and o.key_points == []


def test_toc_map_parse():
    tm = TocMap.model_validate({"assignments": [
        {"index": 1, "title": "评标办法", "categories": ["scoring", "invalidation"]}]})
    assert tm.assignments[0].categories == ["scoring", "invalidation"]
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_schemas.py -v`
Expected: FAIL（ModuleNotFoundError: biaoshu_gen.schemas）

- [ ] **Step 3: 实现 schemas.py**

```python
"""各 LLM 节点的输出模型（PydanticAI output_type）与 YAML 落盘工具。"""
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, Field, ValidationError

T = TypeVar("T", bound=BaseModel)


class TenderMetadata(BaseModel):
    """标书元数据。"""
    project_name: str = ""
    project_no: str = ""
    background: str = ""
    bid_deadline: str = ""       # 投标截止/开标时间
    delivery_date: str = ""      # 交货日期要求
    warranty_period: str = ""    # 质保期要求
    other_commercial: list[str] = Field(default_factory=list)


class TenderRequirements(BaseModel):
    """标书需求。"""
    purchase_list: list[str] = Field(default_factory=list)
    project_overview: str = ""
    tech_requirements: list[str] = Field(default_factory=list)
    implementation_requirements: list[str] = Field(default_factory=list)


class InvalidationItem(BaseModel):
    kind: str = Field(pattern="^(废标项|扣分项)$")
    requirement: str = ""
    source_quote: str = ""       # 招标文件原文依据


class InvalidationItems(BaseModel):
    items: list[InvalidationItem] = Field(default_factory=list)


class ScoringStandards(BaseModel):
    """评标标准。"""
    price_rules: str = ""
    commercial_rules: list[str] = Field(default_factory=list)
    technical_rules: list[str] = Field(default_factory=list)


class GlobalFacts(BaseModel):
    """全局事实设定（人工控制点 1：03_facts.yaml）。"""
    schedule: str = ""           # 工期设置
    staffing: str = ""           # 人员配置
    software_metrics: list[str] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)


class OutlineSection(BaseModel):
    title: str
    target_words: int = 500
    key_points: list[str] = Field(default_factory=list)


class Outline(BaseModel):
    """技术方案目录（人工控制点 2：04_outline.yaml）。"""
    sections: list[OutlineSection] = Field(default_factory=list)
    total_words: int = 0


class SectionBody(BaseModel):
    title: str
    content: str                 # Markdown 正文


class BodyReviewReport(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)


class ParseResult(BaseModel):
    """parse_tender 节点的聚合输出。"""
    metadata: TenderMetadata
    requirements: TenderRequirements
    invalidation: InvalidationItems
    scoring: ScoringStandards


class TocAssignment(BaseModel):
    """章节分类结果：一个章节可同时属于多组。"""
    index: int                      # 章节序号（1 起，与 docx_to_sections 顺序一致）
    title: str
    categories: list[str] = Field(default_factory=list)   # metadata/requirements/invalidation/scoring 子集，可为空


class TocMap(BaseModel):
    assignments: list[TocAssignment] = Field(default_factory=list)


def to_yaml_file(model: BaseModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(model.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def from_yaml_file(cls: type[T], path: Path) -> T:
    """读取并校验；失败抛 ValueError（字段级信息），不静默吞掉用户编辑错误。"""
    try:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValidationError as e:
        detail = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ValueError(f"{path} 校验失败: {detail}") from e
```

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_schemas.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/schemas.py tests/test_schemas.py
git commit -m "feat: 节点输出 schema 与 YAML 读写"
```

---

### Task 3: docx_io.py —— docx 提取 / 写出 / 合并

**Files:**
- Create: `src/biaoshu_gen/docx_io.py`
- Test: `tests/test_docx_io.py`（测试内用 python-docx 现场构造 fixture docx）

**Interfaces:**
- Produces:
  - `DocxSection`（dataclass：`level: int`（0=首个标题前的前言，1~4=Heading N）、`title: str`、`content: str`（本节正文 Markdown，含表格））
  - `docx_to_sections(path: Path) -> list[DocxSection]`（**按标题切章节**——招标解析分节阅读的基础；标题样式同时识别 `Heading N` 与中文 Word 的 `标题 N`）
  - `docx_to_markdown(path: Path) -> str`（基于 sections 拼接的全篇 Markdown；段落+表格按文档顺序，表格输出 pipe 表）
  - `markdown_to_docx(doc: Document, md: str) -> None`（识别 `#`~`####` 标题、`- ` 列表、普通段落）
  - `append_docx(dest: Document, src_path: Path) -> None`（把 src 的 body 元素深拷贝追加到 dest，用于草稿拼装）
  - `copy_docx(src: Path, dest: Path) -> Document`（复制模板并打开）

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

from docx import Document

from biaoshu_gen.docx_io import (
    DocxSection, append_docx, copy_docx, docx_to_markdown, docx_to_sections, markdown_to_docx,
)


def _make_tender_docx(path: Path) -> None:
    doc = Document()
    doc.add_heading("第一章 招标公告", level=1)
    doc.add_paragraph("项目名称：测试项目")
    t = doc.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "名称"
    t.cell(0, 1).text = "数量"
    t.cell(1, 0).text = "应用软件 A"
    t.cell(1, 1).text = "1 套"
    doc.save(path)


def test_docx_to_markdown_keeps_order_and_table(tmp_path: Path):
    p = tmp_path / "t.docx"
    _make_tender_docx(p)
    md = docx_to_markdown(p)
    assert "# 第一章 招标公告" in md
    assert "项目名称：测试项目" in md
    assert "| 名称 | 数量 |" in md
    assert "| 应用软件 A | 1 套 |" in md
    assert md.index("招标公告") < md.index("项目名称") < md.index("应用软件 A")


def test_docx_to_sections_splits_by_heading(tmp_path: Path):
    p = tmp_path / "t2.docx"
    doc = Document()
    doc.add_paragraph("抬头说明")                      # 首个标题前 → 前言
    doc.add_heading("第一章 招标公告", level=1)
    doc.add_paragraph("项目名称：测试项目")
    doc.add_heading("评标办法", level=1)
    doc.add_paragraph("最低价得 100 分")
    doc.save(p)
    secs = docx_to_sections(p)
    assert [(s.level, s.title) for s in secs] == [
        (0, "(前言)"), (1, "第一章 招标公告"), (1, "评标办法")]
    assert "抬头说明" in secs[0].content
    assert "项目名称" in secs[1].content
    assert "100 分" in secs[2].content


def test_markdown_to_docx_headings_and_list(tmp_path: Path):
    doc = Document()
    markdown_to_docx(doc, "# 总体方案\n\n本章说明总体设计。\n\n- 要点一\n- 要点二\n")
    paras = [p.text for p in doc.paragraphs]
    styles = [p.style.name for p in doc.paragraphs]
    assert "总体方案" in paras and "本章说明总体设计。" in paras and "要点一" in paras
    assert any("Heading 1" in s for s in styles)
    assert any("List" in s for s in styles)


def test_append_docx_merges_tables_and_paragraphs(tmp_path: Path):
    src = tmp_path / "src.docx"
    _make_tender_docx(src)
    dest = Document()
    dest.add_paragraph("前言")
    append_docx(dest, src)
    texts = [p.text for p in dest.paragraphs]
    assert "前言" in texts and "第一章 招标公告" in texts
    assert len(dest.tables) == 1 and dest.tables[0].cell(0, 0).text == "名称"


def test_copy_docx(tmp_path: Path):
    src = tmp_path / "tpl.docx"
    _make_tender_docx(src)
    doc = copy_docx(src, tmp_path / "tpl_copy.docx")
    assert "第一章 招标公告" in "\n".join(p.text for p in doc.paragraphs)
    assert (tmp_path / "tpl_copy.docx").exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_docx_io.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 docx_io.py**

```python
"""docx 与 Markdown 的双向转换、模板复制、文档合并。"""
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.table import Table
from docx.text.paragraph import Paragraph


def _iter_block_items(doc: DocumentType):
    """按文档真实顺序产出段落与表格。"""
    from docx.oxml.ns import qn
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _table_md(table: Table) -> str:
    lines = []
    for row in table.rows:
        cells = [c.text.replace("\n", " ").replace("|", "/").strip() for c in row.cells]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


@dataclass
class DocxSection:
    """docx 按标题切出的章节。level=0 表示首个标题前的前言。"""
    level: int          # 0=前言, 1~4=Heading N
    title: str
    content: str        # 本节正文 Markdown（含表格）


_HEADING_RE = re.compile(r"(?:heading|标题)\s*(\d)", re.IGNORECASE)


def docx_to_sections(path: Path) -> list[DocxSection]:
    doc = Document(str(path))
    sections: list[DocxSection] = []
    cur: DocxSection | None = None

    def flush(text: str) -> None:
        nonlocal cur
        if cur is None:
            cur = DocxSection(0, "(前言)", "")
        if text:
            cur.content = (cur.content + "\n\n" + text).strip()

    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            m = _HEADING_RE.match((block.style.name or "").strip())
            if m and text:
                if cur is not None:
                    sections.append(cur)
                cur = DocxSection(int(m.group(1)), text, "")
            else:
                flush(text)
        else:
            flush(_table_md(block))
    if cur is not None:
        sections.append(cur)
    return sections


def docx_to_markdown(path: Path) -> str:
    parts: list[str] = []
    for s in docx_to_sections(path):
        if s.level:
            parts.append("#" * s.level + " " + s.title)
        if s.content:
            parts.append(s.content)
    return "\n\n".join(parts) + "\n"


def markdown_to_docx(doc: DocumentType, md: str) -> None:
    """极量版 Markdown → docx：标题/列表/段落（POC 够用）。"""
    for line in md.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            doc.add_heading(m.group(2), level=len(m.group(1)))
        elif s.startswith(("- ", "* ")):
            doc.add_paragraph(s[2:], style="List Bullet")
        elif re.match(r"^\d+\.\s+", s):
            doc.add_paragraph(re.sub(r"^\d+\.\s+", "", s), style="List Number")
        else:
            doc.add_paragraph(re.sub(r"\*\*(.+?)\*\*", r"\1", s))


def append_docx(dest: DocumentType, src_path: Path) -> None:
    """把 src 文档 body 的段落/表格深拷贝追加到 dest（跨文档移动需要 deepcopy）。"""
    import copy as _copy

    src = Document(str(src_path))
    for child in src.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag in ("p", "tbl"):
            dest.element.body.append(_copy.deepcopy(child))


def copy_docx(src: Path, dest: Path) -> DocumentType:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return Document(str(dest))
```

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_docx_io.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/docx_io.py tests/test_docx_io.py
git commit -m "feat: docx 提取/写出/合并工具"
```

---

### Task 4: kb.py —— 企业知识库加载 + BM25 检索 + 文本工具

**Files:**
- Create: `src/biaoshu_gen/kb.py`
- Test: `tests/test_kb.py`

**Interfaces:**
- Consumes: `docx_io.docx_to_markdown`（Task 3）
- Produces:
  - `KbChunk`（`source: Path`、`text: str`）
  - `KnowledgeBase.load(dir: Path) -> KnowledgeBase`（.txt/.md 直读，.docx 转 Markdown，图片/其他文件只登记路径）
  - `KnowledgeBase.search(query: str, top_k: int | None = None) -> list[KbChunk]`（jieba 分词 + BM25Okapi 排序）
  - `KnowledgeBase.image_paths() -> list[Path]`（供 harness 节点直接引用）
  - `KnowledgeBase.all_files() -> list[Path]`（harness 工作区复制用）
  - `count_chars(text: str) -> int`（非空白字符数，中文字数统计口径）

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

from docx import Document

from biaoshu_gen.kb import KnowledgeBase, count_chars


def _make_kb_dir(tmp_path: Path) -> Path:
    kb = tmp_path / "company"
    kb.mkdir()
    (kb / "简介.md").write_text(
        "公司成立于 2010 年，专注于政务信息化，具备 CMMI5 认证。\n\n"
        "公司拥有软件测试团队，可提供驻场实施与三年质保服务。", encoding="utf-8")
    (kb / "资质.txt").write_text("具备 ISO27001 信息安全认证与 ITSS 运维认证。", encoding="utf-8")
    d = Document()
    d.add_paragraph("成功交付某省一体化政务服务平台，合同额 2000 万。")
    d.save(kb / "案例.docx")
    (kb / "营业执照.jpg").write_bytes(b"\xff\xd8fake")
    return kb


def test_load_and_search(tmp_path: Path):
    kb = KnowledgeBase.load(_make_kb_dir(tmp_path))
    hits = kb.search("信息安全 认证", top_k=2)
    assert hits and "ISO27001" in hits[0].text
    hits2 = kb.search("政务平台 交付案例", top_k=3)
    assert any("政务服务平台" in h.text for h in hits2)


def test_images_registered_not_searched(tmp_path: Path):
    kb = KnowledgeBase.load(_make_kb_dir(tmp_path))
    assert kb.image_paths() == [Path(kb.all_files()[0]).parent / "营业执照.jpg"] or \
           [p.name for p in kb.image_paths()] == ["营业执照.jpg"]
    assert all("fake" != h.text for h in kb.search("营业执照"))


def test_search_empty_kb(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert KnowledgeBase.load(empty).search("任意") == []


def test_count_chars():
    assert count_chars("你好  world\n") == 7
    assert count_chars("") == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_kb.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 kb.py**

```python
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


def count_chars(text: str) -> int:
    """字数统计口径：非空白字符数（正文字数校验使用）。"""
    return len(re.sub(r"\s", "", text))
```

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_kb.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/kb.py tests/test_kb.py
git commit -m "feat: 企业知识库加载与 BM25 检索"
```

---

### Task 5: state.py —— LangGraph 全局状态

**Files:**
- Create: `src/biaoshu_gen/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: Task 2 的全部 schema 类型
- Produces: `BidState(BaseModel)`（字段见代码——所有节点函数签名 `(state: BidState) -> dict`，返回部分字段更新）
- Produces: `run_dir(state: BidState) -> Path`（`data/runs/<run_id>/`，各节点落盘用）

- [ ] **Step 1: 写失败测试**

```python
from biaoshu_gen.state import BidState, run_dir


def test_default_state():
    s = BidState(run_id="run-x")
    assert s.metadata is None and s.body_review_rounds == 0
    assert s.draft_version == 0 and s.revision_round == 0


def test_run_dir():
    s = BidState(run_id="run-x")
    assert run_dir(s).name == "run-x"
    assert run_dir(s).parent.name == "runs"
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_state.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 state.py**

```python
"""LangGraph 全局状态：节点返回 dict 部分更新本模型字段。"""
from pathlib import Path

from pydantic import BaseModel

from .config import get_settings
from .schemas import (
    GlobalFacts, InvalidationItems, Outline, ScoringStandards,
    TenderMetadata, TenderRequirements,
)


class BidState(BaseModel):
    run_id: str = ""
    tender_path: str = ""
    kb_dir: str = ""
    template_docx_path: str = ""      # 招标文件同目录下发现的 *模板*.docx（可为空）

    # 01_parse
    metadata: TenderMetadata | None = None
    requirements: TenderRequirements | None = None
    scoring: ScoringStandards | None = None
    invalidation: InvalidationItems | None = None

    # 02_template
    template_md_path: str = ""
    template_report_path: str = ""

    # 03/04
    facts: GlobalFacts | None = None
    outline: Outline | None = None

    # 05_body
    body_md_path: str = ""
    body_feedback: str = ""           # body_review 给 body 的回环意见
    body_review_rounds: int = 0
    body_review_passed: bool = False

    # 06_fill
    forms_docx_path: str = ""
    deviation_docx_path: str = ""
    commercial_docx_path: str = ""

    # 07_draft
    draft_docx_path: str = ""
    draft_md_path: str = ""
    draft_version: int = 0

    # 08_review
    review_report_path: str = ""
    review_passed: bool = False
    revision_round: int = 0

    errors: list[str] = []


def run_dir(state: BidState) -> Path:
    return get_settings().data_dir / "runs" / state.run_id
```

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_state.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/state.py tests/test_state.py
git commit -m "feat: LangGraph 全局状态 BidState"
```

---

### Task 6: models.py —— PydanticAI Agent 工厂（DeepSeek）

**Files:**
- Create: `src/biaoshu_gen/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `get_settings()`（Task 1）
- Produces: `make_agent(output_type: type, system_prompt: str, retries: int = 2) -> Agent`——所有非 harness 节点经 `from .models import make_agent` 创建 Agent；测试通过 monkeypatch 各节点模块的 `make_agent` 注入假模型

- [ ] **Step 1: 写失败测试**

```python
from biaoshu_gen.models import make_agent
from biaoshu_gen.schemas import GlobalFacts


def test_make_agent_builds_agent_with_output_type():
    agent = make_agent(GlobalFacts, system_prompt="你是投标助手")
    assert agent.output_type is GlobalFacts
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_models.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 models.py**

```python
"""PydanticAI Agent 工厂：DeepSeek（OpenAI 兼容端点）。"""
from pydantic import BaseModel

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel

from .config import get_settings


def make_agent(output_type: type[BaseModel], system_prompt: str, retries: int = 2) -> Agent:
    s = get_settings()
    model = OpenAIChatModel(
        s.deepseek_model,
        base_url=s.deepseek_base_url,
        api_key=s.deepseek_api_key,
    )
    return Agent(model=model, output_type=output_type, system_prompt=system_prompt, retries=retries)
```

注：若所用 pydantic-ai 版本的 `OpenAIChatModel` 不接受 `api_key`/`base_url` 关键字，改用 `OpenAIChatModel(model_name, api_key=..., base_url=...)` 或 `OpenAIProvider(api_key=..., base_url=...)` 传给 `Agent(model=OpenAIChatModel(name, provider=provider))`——以安装版本的实际签名为准，保持工厂函数对外接口不变。

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_models.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/models.py tests/test_models.py
git commit -m "feat: PydanticAI Agent 工厂（DeepSeek）"
```

---

### Task 7: harness.py —— Claude Code SDK 封装（任务下发/产物校验/重试）

**Files:**
- Create: `src/biaoshu_gen/harness.py`
- Test: `tests/test_harness.py`（mock SDK，不真起 claude 进程）

**Interfaces:**
- Consumes: `get_settings().harness_max_turns`（Task 1）
- Produces:
  - `HarnessTask`（dataclass：`prompt: str`、`cwd: Path`、`expected_outputs: list[Path]`、`max_turns: int = 0`——0 表示用 settings 默认）
  - `HarnessError(RuntimeError)`
  - `run_harness_task(task: HarnessTask) -> list[Path]`（调用 `_query_sdk`，产物缺失带反馈重试一次，再缺则抛 `HarnessError`）
  - `async _query_sdk(prompt: str, cwd: Path, max_turns: int) -> str`（真实 SDK 调用；测试 monkeypatch 本函数）
  - `prepare_workspace(run_dir: Path, stage_subdir: str, inputs: list[tuple[Path, str]] | None = None) -> Path`（创建 `run_dir/stage_subdir/`，把每个输入文件复制为指定名）

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

import pytest

from biaoshu_gen import harness
from biaoshu_gen.harness import HarnessError, HarnessTask, prepare_workspace, run_harness_task


def _ok_query(prompt: str, cwd: Path, max_turns: int) -> str:
    for p in Path(cwd).glob("*.md"):
        pass
    (cwd / "expected.md").write_text("done", encoding="utf-8")
    return "已产出 expected.md"


def test_prepare_workspace_copies_inputs(tmp_path: Path):
    src = tmp_path / "a.yaml"
    src.write_text("x: 1", encoding="utf-8")
    ws = prepare_workspace(tmp_path, "02_template", [(src, "input.yaml")])
    assert ws == tmp_path / "02_template"
    assert (ws / "input.yaml").read_text(encoding="utf-8") == "x: 1"


def test_run_harness_task_success(tmp_path: Path, monkeypatch):
    async def fake(prompt, cwd, max_turns):
        return _ok_query(prompt, Path(cwd), max_turns)
    monkeypatch.setattr(harness, "_query_sdk", fake)
    out = tmp_path / "expected.md"
    task = HarnessTask(prompt="做点什么", cwd=tmp_path, expected_outputs=[out])
    assert run_harness_task(task) == [out]


def test_run_harness_task_retries_once_then_raises(tmp_path: Path, monkeypatch):
    calls = []

    async def fake(prompt, cwd, max_turns):
        calls.append(prompt)
        return "什么都没做"
    monkeypatch.setattr(harness, "_query_sdk", fake)
    task = HarnessTask(prompt="做点什么", cwd=tmp_path, expected_outputs=[tmp_path / "expected.md"])
    with pytest.raises(HarnessError) as e:
        run_harness_task(task)
    assert len(calls) == 2                    # 原始 + 重试一次
    assert "expected.md" in str(e.value)
    assert "未产出" in calls[1]               # 重试 prompt 带缺项反馈


def test_run_harness_task_retry_can_succeed(tmp_path: Path, monkeypatch):
    n = 0

    async def fake(prompt, cwd, max_turns):
        nonlocal n
        n += 1
        if n == 2:
            (Path(cwd) / "expected.md").write_text("ok", encoding="utf-8")
        return "r"
    monkeypatch.setattr(harness, "_query_sdk", fake)
    assert run_harness_task(HarnessTask(prompt="p", cwd=tmp_path,
                                        expected_outputs=[tmp_path / "expected.md"]))
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_harness.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 harness.py**

```python
"""Claude Code SDK（claude-agent-sdk）封装：文件操作型 harness 节点统一入口。

SDK 以子进程方式拉起 claude CLI，自动继承本机环境
（ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN → 智谱网关）。
"""
import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import get_settings


class HarnessError(RuntimeError):
    pass


@dataclass
class HarnessTask:
    prompt: str
    cwd: Path
    expected_outputs: list[Path]
    max_turns: int = 0            # 0 → 使用 settings.harness_max_turns


async def _query_sdk(prompt: str, cwd: Path, max_turns: int) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, query

    options = ClaudeAgentOptions(
        cwd=str(cwd),
        max_turns=max_turns,
        permission_mode="bypassPermissions",   # POC 本机受控工作区
    )
    final = ""
    async for msg in query(prompt=prompt, options=options):
        if getattr(msg, "type", "") == "result":
            final = getattr(msg, "result", "") or ""
    return final


def _missing_outputs(paths: list[Path]) -> list[Path]:
    return [p for p in paths if not p.exists() or p.stat().st_size == 0]


def run_harness_task(task: HarnessTask) -> list[Path]:
    """执行任务；产物缺失 → 带反馈重试一次 → 仍缺失则抛 HarnessError。"""
    max_turns = task.max_turns or get_settings().harness_max_turns
    first = asyncio.run(_query_sdk(task.prompt, task.cwd, max_turns))
    missing = _missing_outputs(task.expected_outputs)
    if missing:
        retry = (
            task.prompt
            + "\n\n【重试提示】上次运行未产出以下文件，请务必产出：\n"
            + "\n".join(str(p) for p in missing)
            + f"\n\n上次运行最终输出（截断）：\n{first[-2000:]}"
        )
        asyncio.run(_query_sdk(retry, task.cwd, max_turns))
        missing = _missing_outputs(task.expected_outputs)
    if missing:
        raise HarnessError("harness 未产出: " + ", ".join(str(p) for p in missing))
    return list(task.expected_outputs)


def prepare_workspace(run_dir: Path, stage_subdir: str,
                      inputs: list[tuple[Path, str]] | None = None) -> Path:
    ws = run_dir / stage_subdir
    ws.mkdir(parents=True, exist_ok=True)
    for src, name in inputs or []:
        target = ws / name
        if not target.exists():
            shutil.copyfile(src, target)
    return ws
```

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_harness.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/harness.py tests/test_harness.py
git commit -m "feat: Claude Code SDK harness 封装与工作区准备"
```

---

### Task 8: parse_tender 节点（目录分节阅读）+ prompts 机制 + 测试基建

**Files:**
- Create: `src/biaoshu_gen/prompts/__init__.py`（空）
- Create: `src/biaoshu_gen/prompts/parse_tender.py`
- Create: `src/biaoshu_gen/nodes/__init__.py`（DEFAULT_NODES 机制）
- Create: `src/biaoshu_gen/nodes/parse_tender.py`
- Create: `tests/conftest.py`（假 Agent 工厂 fixture，后续 LLM 节点任务复用）
- Test: `tests/test_node_parse_tender.py`

**Interfaces:**
- Consumes: `make_agent`（Task 6）、`docx_to_sections`/`docx_to_markdown`（Task 3）、`TocMap`/`to_yaml_file`（Task 2）、`run_dir`（Task 5）
- Produces:
  - `nodes.parse_tender.parse_tender_node(state: BidState) -> dict`：**按目录分节阅读**——① 仅用目录标题行调用 `TocMap` 做章节分类（避免整篇长上下文）；② 按组拼接本组章节内容分别抽取（单组超 24000 字符按整节分批、代码侧合并）；③ 关键词兜底：标题含 废标/无效/扣分/偏离 的章节强制并入 invalidation 组；写 `01_parse/{metadata,requirements,scoring,invalidation}.yaml` 与 `01_parse/tender.md`（后续 harness 节点输入），返回 4 个 schema 字段更新
  - `prompts.parse_tender.SYSTEM_CLASSIFY`、`build_classify_prompt(toc_lines: list[str]) -> str`、`SYSTEM_EXTRACT`、`build_extract_prompt(group_desc: str, sections_text: str) -> str`
  - `nodes/__init__.py`：`NODE_NAMES: list[str]`（12 个节点名，固定顺序）、`DEFAULT_NODES: dict[str, NodeFn]`（未实现节点为抛 `NotImplementedError` 的 stub；每实现一个节点就替换对应条目）、`get_nodes(overrides: dict[str, NodeFn] | None) -> dict[str, NodeFn]`
  - `tests/conftest.py`：pytest fixture `fake_agent_factory`（参数：按 output_type 返回预设 dict 的假 Agent），后续 LLM 节点测试注入用

- [ ] **Step 1: 写 conftest.py 假 Agent 工厂**

```python
"""测试基建：给 LLM 节点注入假模型的 Agent 工厂（PydanticAI FunctionModel）。"""
import pytest
from pydantic_ai import Agent
from pydantic_ai.models.function import AgentInfo, FunctionModel


def _make_fake_agent(overrides: dict, default: dict, system_prompt: str, retries: int):
    async def fn(messages, info: AgentInfo):
        out = overrides.get(info.output_type, default)
        return out
    return Agent(model=FunctionModel(fn), system_prompt=system_prompt, retries=retries)


@pytest.fixture
def fake_agent_factory():
    """用法：monkeypatch.setattr(node_mod, 'make_agent', fake_agent_factory({ParseResult: {...}}))"""
    def _factory(overrides: dict, default: dict | None = None):
        def make(output_type, system_prompt, retries=2):
            return _make_fake_agent(overrides, default or {}, system_prompt, retries)
        return make
    return _factory
```

- [ ] **Step 2: 写失败测试**

```python
from pathlib import Path

from docx import Document

from biaoshu_gen.nodes import DEFAULT_NODES, NODE_NAMES
from biaoshu_gen.nodes import parse_tender as pt
from biaoshu_gen.schemas import (
    InvalidationItems, ScoringStandards, TocMap, TenderMetadata, TenderRequirements,
)
from biaoshu_gen.state import BidState, run_dir


def _state(tmp_path: Path, monkeypatch) -> BidState:
    monkeypatch.chdir(tmp_path)   # data_dir 相对路径 → tmp
    tender = tmp_path / "tender.docx"
    d = Document()
    d.add_heading("第一章 招标公告", level=1)
    d.add_paragraph("项目名称：演示项目")
    d.add_heading("第二章 技术要求", level=1)
    d.add_paragraph("系统需支持 1000 并发。")
    d.add_heading("第三章 评标办法", level=1)
    d.add_paragraph("价格分：最低价得 100 分。")
    d.save(tender)
    return BidState(run_id="run-1", tender_path=str(tender))


def test_node_names_registry():
    assert NODE_NAMES[0] == "parse_tender" and len(NODE_NAMES) == 12
    assert DEFAULT_NODES["parse_tender"] is pt.parse_tender_node
    assert callable(DEFAULT_NODES["extract_template"])  # 未实现 → stub


def test_parse_tender_routes_sections_by_toc(tmp_path: Path, monkeypatch):
    state = _state(tmp_path, monkeypatch)
    captured: list[tuple[type, str]] = []

    def make(output_type, system_prompt, retries=2):
        from pydantic_ai import Agent
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        async def fn(messages, info: AgentInfo):
            captured.append((info.output_type, str(messages[-1].content)))
            if info.output_type is TocMap:
                return {"assignments": [
                    {"index": 1, "title": "第一章 招标公告", "categories": ["metadata"]},
                    {"index": 2, "title": "第二章 技术要求", "categories": ["requirements"]},
                    {"index": 3, "title": "第三章 评标办法", "categories": ["scoring"]},
                ]}
            if info.output_type is TenderMetadata:
                return {"project_name": "演示项目"}
            if info.output_type is TenderRequirements:
                return {"tech_requirements": ["1000 并发"]}
            if info.output_type is ScoringStandards:
                return {"price_rules": "最低价得 100 分"}
            return {"items": []}
        return Agent(model=FunctionModel(fn), system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(pt, "make_agent", make)
    updates = pt.parse_tender_node(state)

    d = run_dir(state) / "01_parse"
    assert (d / "tender.md").exists()
    assert (d / "metadata.yaml").exists() and (d / "scoring.yaml").exists()
    assert updates["metadata"].project_name == "演示项目"
    assert updates["requirements"].tech_requirements == ["1000 并发"]

    # 分节路由断言：分类调用只看到目录行；每组抽取只看到本组章节内容
    toc_prompt = next(p for t, p in captured if t is TocMap)
    assert "招标公告" in toc_prompt and "项目名称" not in toc_prompt
    meta_prompt = next(p for t, p in captured if t is TenderMetadata)
    assert "项目名称：演示项目" in meta_prompt and "评标办法" not in meta_prompt
    scoring_prompt = next(p for t, p in captured if t is ScoringStandards)
    assert "最低价得 100 分" in scoring_prompt and "技术要求" not in scoring_prompt


def test_parse_tender_keyword_sections_forced_to_invalidation(tmp_path: Path, monkeypatch):
    """标题含 废标/无效/扣分/偏离 的章节，即使分类遗漏也强制并入 invalidation 组。"""
    monkeypatch.chdir(tmp_path)
    tender = tmp_path / "t2.docx"
    d = Document()
    d.add_heading("废标条款", level=1)
    d.add_paragraph("逾期送达的投标文件将被拒收。")
    d.save(tender)
    state = BidState(run_id="run-2", tender_path=str(tender))

    def make(output_type, system_prompt, retries=2):
        from pydantic_ai import Agent
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        async def fn(messages, info: AgentInfo):
            if info.output_type is TocMap:
                return {"assignments": [{"index": 1, "title": "废标条款", "categories": []}]}
            if info.output_type is InvalidationItems:
                return {"items": [{"kind": "废标项", "requirement": "不得逾期送达"}]}
            return {}
        return Agent(model=FunctionModel(fn), system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(pt, "make_agent", make)
    updates = pt.parse_tender_node(state)
    assert updates["invalidation"].items[0].kind == "废标项"   # 兜底路由使抽取确实发生
```

- [ ] **Step 3: 运行确认失败**

Run: `poetry run pytest tests/test_node_parse_tender.py -v`
Expected: FAIL（nodes 包不存在）

- [ ] **Step 4: 实现 prompts/parse_tender.py、nodes/__init__.py、nodes/parse_tender.py**

`prompts/parse_tender.py`:

```python
"""招标文件解析节点 prompt：目录分类 + 分组抽取（分节阅读，避免整篇长上下文）。"""

SYSTEM_CLASSIFY = "你是招标文件结构分析员。只依据给出的目录（章节标题）判断每章属于哪些信息组。"

CLASSIFY_TEMPLATE = """以下是招标文件的目录（章节标题，含序号）：

{toc_lines}

信息组定义：
- metadata：项目名称/编号、投标截止、交货日期、质保期等商务元数据（常见于招标公告/邀请书/投标人须知）
- requirements：采购清单、项目概况、技术要求、实施要求（常见于需求书/技术规范/采购内容章节）
- invalidation：废标项、无效投标、扣分项、偏离要求（常见于评标办法/无效投标条款/废标条款）
- scoring：价格/商务/技术评分标准（常见于评标办法/评分细则）
- 都不属于 → categories 返回空列表

每个章节输出一个 TocAssignment（index 与目录序号一致）；一个章节可同时属于多组。"""


def build_classify_prompt(toc_lines: list[str]) -> str:
    return CLASSIFY_TEMPLATE.format(toc_lines="\n".join(toc_lines))


SYSTEM_EXTRACT = "你是资深软件投标分析师。只依据给出的章节内容抽取信息，原文没有的留空/空列表，不得臆造。"

EXTRACT_TEMPLATE = """从以下招标文件章节内容中抽取「{group_desc}」：

{sections_text}

要求：
- 只依据原文，不得臆造
- 若本批次无相关信息：字符串字段留空、列表字段返回空列表
- 废标项/扣分项需给出原文依据（source_quote）"""


def build_extract_prompt(group_desc: str, sections_text: str) -> str:
    return EXTRACT_TEMPLATE.format(group_desc=group_desc, sections_text=sections_text)
```

`nodes/__init__.py`:

```python
"""节点注册表：未实现的节点为 stub，实现后在 REAL_IMPORTS 处登记。"""
from collections.abc import Callable

from ..state import BidState

NodeFn = Callable[[BidState], dict]

NODE_NAMES = [
    "parse_tender", "extract_template", "facts", "outline",
    "body", "body_review",
    "fill_forms", "deviation_table", "commercial",
    "assemble", "review", "revise",
]


def _stub(name: str) -> NodeFn:
    def f(state: BidState) -> dict:
        raise NotImplementedError(f"节点 {name} 尚未实现")
    f.__name__ = f"{name}_stub"
    return f


DEFAULT_NODES: dict[str, NodeFn] = {n: _stub(n) for n in NODE_NAMES}

# --- 已实现节点登记（逐任务补充） ---
from .parse_tender import parse_tender_node          # noqa: E402
DEFAULT_NODES["parse_tender"] = parse_tender_node


def get_nodes(overrides: dict[str, NodeFn] | None = None) -> dict[str, NodeFn]:
    nodes = dict(DEFAULT_NODES)
    nodes.update(overrides or {})
    return nodes
```

`nodes/parse_tender.py`:

```python
"""节点 1：招标文件解析——按目录分节阅读：目录分类 → 分组抽取 → 合并落盘。"""
from pathlib import Path

from pydantic import BaseModel

from ..docx_io import DocxSection, docx_to_markdown, docx_to_sections
from ..models import make_agent
from ..prompts.parse_tender import (
    SYSTEM_CLASSIFY, SYSTEM_EXTRACT, build_classify_prompt, build_extract_prompt,
)
from ..schemas import (
    InvalidationItems, ScoringStandards, TocMap, TenderMetadata, TenderRequirements,
    to_yaml_file,
)
from ..state import BidState, run_dir

# 每组抽取的输出类型与说明（进入抽取 prompt）
GROUPS: dict[str, tuple[type[BaseModel], str]] = {
    "metadata": (TenderMetadata,
                 "标书元数据：项目名称/编号、项目背景、投标截止、交货日期、质保期等"),
    "requirements": (TenderRequirements,
                     "标书需求：采购清单、项目概况、技术要求（逐条）、实施要求（逐条）"),
    "invalidation": (InvalidationItems,
                     "废标项+扣分项：逐条给出 kind(废标项|扣分项)/requirement/source_quote"),
    "scoring": (ScoringStandards,
                "评标标准：价格评分规则、商务评分规则（逐条）、技术评分规则（逐条）"),
}
_INVALIDATION_KEYWORDS = ("废标", "无效", "扣分", "偏离")
_MAX_BATCH_CHARS = 24000


def _toc_lines(sections: list[DocxSection]) -> list[str]:
    return [f"{i}. {s.title}" for i, s in enumerate(sections, 1)]


def _batches(sections: list[DocxSection]) -> list[list[DocxSection]]:
    """按整节组批（≤_MAX_BATCH_CHARS）；单节超长再按段落硬切。"""
    batches: list[list[DocxSection]] = []
    buf: list[DocxSection] = []
    size = 0
    for s in sections:
        if len(s.content) > _MAX_BATCH_CHARS:
            if buf:
                batches.append(buf)
                buf, size = [], 0
            paras = s.content.split("\n\n")
            acc: list[str] = []
            acc_size = 0
            for para in paras:
                acc.append(para)
                acc_size += len(para)
                if acc_size >= _MAX_BATCH_CHARS:
                    batches.append([DocxSection(s.level, s.title, "\n\n".join(acc))])
                    acc, acc_size = [], 0
            if acc:
                batches.append([DocxSection(s.level, s.title, "\n\n".join(acc))])
            continue
        if size + len(s.content) > _MAX_BATCH_CHARS and buf:
            batches.append(buf)
            buf, size = [], 0
        buf.append(s)
        size += len(s.content)
    if buf:
        batches.append(buf)
    return batches


def _merge(objs: list[BaseModel]) -> BaseModel:
    """同组多批次结果合并：str 取第一个非空；list 拼接去重（保持顺序）。"""
    merged: dict = {}
    for name in type(objs[0]).model_fields:
        values = [getattr(o, name) for o in objs]
        first = values[0]
        if isinstance(first, list):
            seen: set = set()
            out: list = []
            for v in values:
                for item in v:
                    key = item if isinstance(item, str) else (
                        item.model_dump_json() if hasattr(item, "model_dump_json") else str(item))
                    if key not in seen:
                        seen.add(key)
                        out.append(item)
            merged[name] = out
        elif isinstance(first, str):
            merged[name] = next((v for v in values if v), "")
        else:
            merged[name] = values[-1]
    return type(objs[0]).model_validate(merged)


def parse_tender_node(state: BidState) -> dict:
    sections = docx_to_sections(Path(state.tender_path))

    # ① 目录分类：只有标题行进入此调用
    toc: TocMap = make_agent(TocMap, SYSTEM_CLASSIFY).run_sync(
        build_classify_prompt(_toc_lines(sections))).output
    by_group: dict[str, list[int]] = {g: [] for g in GROUPS}
    for a in toc.assignments:
        for g in a.categories:
            if g in by_group and 1 <= a.index <= len(sections):
                by_group[g].append(a.index)
    # 关键词兜底：标题命中 废标/无效/扣分/偏离 的章节强制并入 invalidation
    for i, s in enumerate(sections, 1):
        if any(k in s.title for k in _INVALIDATION_KEYWORDS) and i not in by_group["invalidation"]:
            by_group["invalidation"].append(i)

    # ② 分组抽取：每组只拼接本组章节内容
    results: dict[str, BaseModel] = {}
    for group, (tp, desc) in GROUPS.items():
        group_sections = [sections[i - 1] for i in sorted(set(by_group[group]))]
        if not group_sections:
            results[group] = tp()
            continue
        objs = [
            make_agent(tp, SYSTEM_EXTRACT).run_sync(
                build_extract_prompt(desc, "\n\n".join(
                    (f"{'#' * s.level} {s.title}\n\n" if s.level else "") + s.content
                    for s in batch))).output
            for batch in _batches(group_sections)
        ]
        results[group] = _merge(objs) if len(objs) > 1 else objs[0]

    # ③ 落盘（tender.md 全文供后续 harness 节点使用）
    d = run_dir(state) / "01_parse"
    d.mkdir(parents=True, exist_ok=True)
    (d / "tender.md").write_text(docx_to_markdown(Path(state.tender_path)), encoding="utf-8")
    to_yaml_file(results["metadata"], d / "metadata.yaml")
    to_yaml_file(results["requirements"], d / "requirements.yaml")
    to_yaml_file(results["invalidation"], d / "invalidation.yaml")
    to_yaml_file(results["scoring"], d / "scoring.yaml")
    return {
        "metadata": results["metadata"],
        "requirements": results["requirements"],
        "invalidation": results["invalidation"],
        "scoring": results["scoring"],
    }
```

注：`_merge` 的列表去重保持首次出现顺序，`InvalidationItem` 用 `model_dump_json` 作去重键。

- [ ] **Step 5: 运行测试通过**

Run: `poetry run pytest tests/test_node_parse_tender.py tests/conftest.py -v`（conftest 无测试，跑整个 tests 也行：`poetry run pytest -v`）
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add src/biaoshu_gen/prompts src/biaoshu_gen/nodes tests/conftest.py tests/test_node_parse_tender.py
git commit -m "feat: 招标解析节点与节点注册表/测试基建"
```

---

### Task 9: graph.py —— 状态图构建 + 阶段路由

**Files:**
- Create: `src/biaoshu_gen/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `get_nodes`（Task 8）、`BidState`（Task 5）、`get_settings()`（Task 1）
- Produces:
  - `STAGES: dict[str, StageSpec]`（`StageSpec(members: tuple[str, ...], end_nodes: tuple[str, ...])`）、`STAGE_ORDER: list[str]`
  - `build_graph(node_overrides: dict[str, NodeFn] | None = None, checkpointer=None) -> CompiledStateGraph`
  - `route_after_body_review(state: BidState) -> str | list[str]`（回 `"body"` 或 `["fill_forms", "deviation_table", "commercial"]`）
  - `route_after_review(state: BidState) -> str`（回 `END` 或 `"revise"`）
  - 图结构（边集）：
    `START→parse_tender→extract_template→facts→outline→body→body_review`；
    `body_review` 条件边→`body`（回环）或 fan-out 三填充节点；三填充节点→`assemble→review`；`review` 条件边→`revise` 或 `END`；`revise→review`

- [ ] **Step 1: 写失败测试（用假节点验证图结构、回环收敛、阶段停止）**

```python
import sqlite3
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END

from biaoshu_gen import graph as g
from biaoshu_gen.state import BidState


def _saver(tmp_path: Path) -> SqliteSaver:
    return SqliteSaver(sqlite3.connect(tmp_path / "ck.db", check_same_thread=False))


def _fakes(spec: dict[str, int]) -> dict:
    """spec: 节点名 → 该节点把 counter 字段 +1 的次数无意义；这里用闭包记录调用。"""
    calls: dict[str, int] = {}
    nodes = {}
    for name in g.NODE_NAMES:
        def make(n):
            def fn(state: BidState) -> dict:
                calls[n] = calls.get(n, 0) + 1
                if n == "body_review":
                    passed = calls["body"] >= 2        # 第 2 次正文后通过
                    return {"body_review_passed": passed,
                            "body_review_rounds": state.body_review_rounds + 1,
                            "body_feedback": "" if passed else "补充实施计划"}
                if n == "review":
                    passed = calls.get("revise", 0) >= 1   # 修改一轮后通过
                    return {"review_passed": passed}
                if n == "revise":
                    return {"revision_round": state.revision_round + 1,
                            "draft_version": state.draft_version + 1}
                return {}
            return fn
        nodes[name] = make(name)
    nodes["_calls"] = calls
    return nodes


def test_stage_specs_cover_all_nodes():
    members = [n for spec in g.STAGES.values() for n in spec.members]
    assert sorted(members) == sorted(g.NODE_NAMES)
    assert g.STAGE_ORDER[0] == "parse" and g.STAGE_ORDER[-1] == "revise"


def test_graph_topology():
    graph = g.build_graph(node_overrides={n: (lambda s: {}) for n in g.NODE_NAMES})
    # 用 get_graph 结构断言关键边
    structure = graph.get_graph()
    edges = {(e.source, e.target) for e in structure.edges}
    assert ("__start__", "parse_tender") in edges
    assert ("parse_tender", "extract_template") in edges
    assert ("body_review", "fill_forms") in edges
    assert ("fill_forms", "assemble") in edges
    assert ("revise", "review") in edges


def test_route_after_body_review_and_review():
    s = BidState(body_review_passed=False, body_review_rounds=1)
    assert g.route_after_body_review(s) == "body"
    s2 = BidState(body_review_passed=False, body_review_rounds=2)
    assert g.route_after_body_review(s2) == ["fill_forms", "deviation_table", "commercial"]
    s3 = BidState(review_passed=False, revision_round=0)
    assert g.route_after_review(s3) == "revise"
    s4 = BidState(review_passed=True)
    assert g.route_after_review(s4) == END
    s5 = BidState(review_passed=False, revision_round=2)
    assert g.route_after_review(s5) == END


def test_full_run_loops_converge(tmp_path: Path):
    fakes = _fakes({})
    overrides = {k: v for k, v in fakes.items() if k != "_calls"}
    graph = g.build_graph(node_overrides=overrides, checkpointer=_saver(tmp_path))
    init = {"run_id": "r1", "tender_path": "x.docx", "kb_dir": "kb"}
    graph.invoke(init, {"configurable": {"thread_id": "r1"}})
    calls = fakes["_calls"]
    assert calls["body"] == 2 and calls["body_review"] == 2      # 回环 1 次后通过
    assert calls["revise"] == 1 and calls["review"] == 2         # 修改 1 轮后通过
    assert calls["assemble"] == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_graph.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 graph.py**

```python
"""单一 StateGraph：严格对应设计文档全局流程图，含两条条件回边。"""
from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .config import get_settings
from .nodes import NodeFn, get_nodes
from .state import BidState


@dataclass(frozen=True)
class StageSpec:
    members: tuple[str, ...]
    end_nodes: tuple[str, ...]


STAGES = {
    "parse":    StageSpec(("parse_tender",), ("parse_tender",)),
    "template": StageSpec(("extract_template",), ("extract_template",)),
    "facts":    StageSpec(("facts",), ("facts",)),
    "outline":  StageSpec(("outline",), ("outline",)),
    "body":     StageSpec(("body", "body_review"), ("body_review",)),
    "fill":     StageSpec(("fill_forms", "deviation_table", "commercial"),
                          ("fill_forms", "deviation_table", "commercial")),
    "assemble": StageSpec(("assemble",), ("assemble",)),
    "review":   StageSpec(("review",), ("review",)),
    "revise":   StageSpec(("revise",), ("revise",)),
}
STAGE_ORDER = ["parse", "template", "facts", "outline", "body",
               "fill", "assemble", "review", "revise"]

FILL_NODES = ["fill_forms", "deviation_table", "commercial"]


def route_after_body_review(state: BidState) -> str | list[str]:
    s = get_settings()
    if not state.body_review_passed and state.body_review_rounds < s.body_review_max_rounds:
        return "body"
    return FILL_NODES


def route_after_review(state: BidState) -> str:
    s = get_settings()
    if state.review_passed:
        return END
    if state.revision_round < s.revise_max_rounds:
        return "revise"
    return END


def build_graph(node_overrides: dict[str, NodeFn] | None = None,
                checkpointer=None) -> CompiledStateGraph:
    builder = StateGraph(BidState)
    for name, fn in get_nodes(node_overrides).items():
        builder.add_node(name, fn)
    builder.add_edge(START, "parse_tender")
    for a, b in [("parse_tender", "extract_template"), ("extract_template", "facts"),
                 ("facts", "outline"), ("outline", "body"), ("body", "body_review")]:
        builder.add_edge(a, b)
    builder.add_conditional_edges("body_review", route_after_body_review)
    for n in FILL_NODES:
        builder.add_edge(n, "assemble")
    builder.add_edge("assemble", "review")
    builder.add_conditional_edges("review", route_after_review)
    builder.add_edge("revise", "review")
    return builder.compile(checkpointer=checkpointer)
```

注意：`route_after_body_review` 返回列表时 LangGraph 需要能解析目标名——`add_conditional_edges` 不传 path_map 时直接用返回值（字符串或字符串列表均可）。若所用版本要求显式 path_map，改为 `add_conditional_edges("body_review", route_after_body_review, {"body": "body", "fill_forms": "fill_forms", "deviation_table": "deviation_table", "commercial": "commercial"})` 与 `add_conditional_edges("review", route_after_review, {"revise": "revise", END: END})`（以安装版本为准，测试会立刻暴露）。

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_graph.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/graph.py tests/test_graph.py
git commit -m "feat: LangGraph 全流程状态图与阶段路由"
```

---

### Task 10: cli.py —— 分阶段子命令 + 断点续跑执行器 + init/status

**Files:**
- Modify: `src/biaoshu_gen/cli.py`（替换 Task 1 空壳）
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_graph`/`STAGES`/`STAGE_ORDER`（Task 9）、`get_settings()`（Task 1）
- Produces（typer 命令，均支持 `--run-id`，缺省取 `data/runs/.latest`）:
  - `init --tender <docx> [--kb <dir>] [--run-id <id>]`：创建 `data/runs/<run_id>/run.json`（含自动发现招标文件同目录 `*模板*.docx`）并写 `.latest`
  - `parse` / `template` / `facts` / `outline` / `body` / `fill` / `assemble` / `review`：恢复 checkpoint 跑到对应阶段后停
  - `revise`：恢复后不再设中断，跑完 review↔revise 循环到 END
  - `run`：`_run_stage(None, ...)` 全自动到 END（冒烟）
  - `status`：打印 run 信息与各阶段产物存在性清单
  - 内部 `execute_stage(graph, run_id, stage, initial_input)`：`interrupt_after=end_nodes` + 循环 `invoke(None)` 直到 `snap.next` 为空或已越过本阶段成员节点
  - 内部 `_run_stage(stage, run_id_opt)`：异常写 `runs/<id>/error.log` 并以退出码 1 结束

- [ ] **Step 1: 写失败测试（假节点注入，验证分阶段停止与续跑）**

```python
import sqlite3
from pathlib import Path

from docx import Document
from langgraph.checkpoint.sqlite import SqliteSaver
from typer.testing import CliRunner

from biaoshu_gen import cli
from biaoshu_gen import graph as g
from biaoshu_gen.state import BidState

runner = CliRunner()


def _install_fake_graph(tmp_path: Path, calls: list, monkeypatch) -> None:
    def build(node_overrides=None, checkpointer=None):
        overrides = {}
        for n in g.NODE_NAMES:
            def make(nn):
                def fn(state: BidState) -> dict:
                    calls.append(nn)
                    if nn == "body_review":
                        return {"body_review_passed": True,
                                "body_review_rounds": state.body_review_rounds + 1}
                    if nn == "review":
                        return {"review_passed": True}
                    if nn == "revise":
                        return {"revision_round": state.revision_round + 1}
                    return {}
                return fn
            overrides[n] = make(n)
        return g.build_graph(node_overrides=overrides, checkpointer=checkpointer)
    monkeypatch.setattr(cli, "build_graph", build)


def _init_run(tmp_path: Path) -> None:
    t = tmp_path / "软件招标文件.docx"
    Document().save(t)
    r = runner.invoke(cli.app, ["init", "--tender", str(t), "--kb", str(tmp_path / "kb")])
    assert r.exit_code == 0, r.output


def test_init_creates_run_json_and_latest(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_run(tmp_path)
    runs = tmp_path / "data" / "runs"
    latest = (runs / ".latest").read_text(encoding="utf-8")
    assert (runs / latest / "run.json").exists()


def test_stages_stop_and_resume(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls: list = []
    _install_fake_graph(tmp_path, calls, monkeypatch)
    _init_run(tmp_path)
    assert runner.invoke(cli.app, ["parse"]).exit_code == 0
    assert calls == ["parse_tender"]
    assert runner.invoke(cli.app, ["facts"]).exit_code == 0
    assert calls == ["parse_tender", "extract_template", "facts"]
    assert runner.invoke(cli.app, ["template"]).exit_code == 0   # 已完成 → 不重复执行
    assert calls == ["parse_tender", "extract_template", "facts"]


def test_run_all_reaches_end(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls: list = []
    _install_fake_graph(tmp_path, calls, monkeypatch)
    _init_run(tmp_path)
    assert runner.invoke(cli.app, ["run"]).exit_code == 0
    assert calls.count("review") >= 1 and calls[-1] in ("review", "revise")


def test_status_lists_stages(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _init_run(tmp_path)
    r = runner.invoke(cli.app, ["status"])
    assert r.exit_code == 0 and "parse" in r.output
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_cli.py -v`
Expected: FAIL（cli 无这些命令）

- [ ] **Step 3: 实现 cli.py（完整替换空壳）**

```python
"""typer CLI：分阶段子命令 = 恢复 checkpoint 跑到对应阶段后停。"""
import json
import sqlite3
import traceback
from datetime import datetime
from pathlib import Path

import typer
from langgraph.checkpoint.sqlite import SqliteSaver

from .config import get_settings
from .graph import STAGES, STAGE_ORDER, build_graph

app = typer.Typer(help="软件标书智能体 POC", no_args_is_help=True)

INIT_FIELDS = ("run_id", "tender_path", "kb_dir", "template_docx_path")


def runs_root() -> Path:
    return get_settings().data_dir / "runs"


def _resolve_run_id(run_id: str | None) -> str:
    if run_id:
        return run_id
    latest = runs_root() / ".latest"
    if latest.exists():
        return latest.read_text(encoding="utf-8").strip()
    ids = sorted(p.name for p in runs_root().iterdir() if p.is_dir()) if runs_root().exists() else []
    if not ids:
        raise typer.BadParameter("没有可用 run，请先执行 biaoshu init")
    return ids[-1]


def _load_run(run_id: str) -> dict:
    run_json = runs_root() / run_id / "run.json"
    if not run_json.exists():
        raise typer.BadParameter(f"run 不存在: {run_json}")
    return json.loads(run_json.read_text(encoding="utf-8"))


def _build_graph_for_run(run_dir: Path):
    conn = sqlite3.connect(run_dir / "checkpoint.sqlite", check_same_thread=False)
    return build_graph(checkpointer=SqliteSaver(conn))


def execute_stage(graph, run_id: str, stage: str | None, initial_input: dict | None) -> None:
    """恢复 checkpoint 跑到指定阶段；stage 为 None 或 'revise' 时跑到 END。"""
    config = {"configurable": {"thread_id": run_id}}
    if stage and stage != "revise":
        config["interrupt_after"] = list(STAGES[stage].end_nodes)
    snap = graph.get_state(config)
    graph.invoke(initial_input if not snap.values else None, config)
    while True:
        snap = graph.get_state(config)
        if not snap.next:                                   # 已到 END
            break
        if stage and stage != "revise" and not (set(snap.next) & set(STAGES[stage].members)):
            break                                           # 下一工作已越出本阶段
        graph.invoke(None, config)


def _run_stage(stage: str | None, run_id_opt: str | None) -> None:
    rid = _resolve_run_id(run_id_opt)
    run = _load_run(rid)
    graph = _build_graph_for_run(runs_root() / rid)
    snap = graph.get_state({"configurable": {"thread_id": rid}})
    initial = {k: run[k] for k in INIT_FIELDS if run.get(k)} if not snap.values else None
    try:
        execute_stage(graph, rid, stage, initial)
    except Exception as e:
        err = runs_root() / rid / "error.log"
        err.parent.mkdir(parents=True, exist_ok=True)
        err.write_text(f"{e}\n\n{traceback.format_exc()}", encoding="utf-8")
        typer.secho(f"阶段执行失败，详情见 {err}", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"完成: {stage or '全部流程'}", fg=typer.colors.GREEN)


@app.command()
def init(
    tender: Path = typer.Option(..., exists=True, dir_okay=False, help="招标文件 docx"),
    kb: Path = typer.Option(Path("data/company"), help="企业信息知识库目录"),
    run_id: str = typer.Option(None, help="run 标识，缺省按时间生成"),
) -> None:
    """创建 run 目录与 run.json。"""
    rid = run_id or datetime.now().strftime("run-%Y%m%d-%H%M%S")
    run_dir = runs_root() / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    template = next(
        (p for p in sorted(tender.parent.glob("*.docx"))
         if "模板" in p.stem and p.resolve() != tender.resolve()), None)
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": rid,
        "tender_path": str(tender.resolve()),
        "kb_dir": str(kb.resolve()),
        "template_docx_path": str(template.resolve()) if template else "",
        "created_at": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (runs_root() / ".latest").parent.mkdir(parents=True, exist_ok=True)
    (runs_root() / ".latest").write_text(rid, encoding="utf-8")
    typer.secho(f"run 已创建: {run_dir}", fg=typer.colors.GREEN)
    if template:
        typer.echo(f"自动发现响应模板: {template}")


def _make_stage_command(stage: str):
    def cmd(run_id: str | None = typer.Option(None, "--run-id")) -> None:
        _run_stage(stage, run_id)
    cmd.__name__ = stage
    cmd.__doc__ = f"执行并停在 {stage} 阶段之后。"
    return cmd


for _stage in STAGE_ORDER:
    app.command(_stage)(_make_stage_command(_stage))


@app.command()
def run(run_id: str | None = typer.Option(None, "--run-id")) -> None:
    """全自动执行全部流程（端到端冒烟）。"""
    _run_stage(None, run_id)


@app.command()
def status(run_id: str | None = typer.Option(None, "--run-id")) -> None:
    """查看 run 进度与产物清单。"""
    rid = _resolve_run_id(run_id)
    run = _load_run(rid)
    run_dir = runs_root() / rid
    typer.echo(f"run: {rid}")
    typer.echo(f"招标文件: {run.get('tender_path')}")
    typer.echo(f"知识库: {run.get('kb_dir')}")
    for name, path in [
        ("parse", run_dir / "01_parse" / "metadata.yaml"),
        ("template", run_dir / "02_template" / "template.md"),
        ("facts", run_dir / "03_facts.yaml"),
        ("outline", run_dir / "04_outline.yaml"),
        ("body", run_dir / "05_body" / "body.md"),
        ("fill", run_dir / "06_fill" / "forms" / "forms.docx"),
        ("assemble", run_dir / "07_draft" / "latest.txt"),
        ("review", run_dir / "08_review" / "review_round_1.md"),
    ]:
        mark = "[x]" if path.exists() else "[ ]"
        typer.echo(f"  {mark} {name}: {path}")


def main() -> None:
    app()
```

说明：`revise` 命令由循环注册（`STAGE_ORDER` 含 `revise`），`execute_stage` 对 `revise` 特殊处理为不设中断跑到 END，语义是"执行修改并跑完循环"。

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_cli.py -v`
Expected: 4 passed

- [ ] **Step 5: 手动验证命令注册**

Run: `poetry run biaoshu --help`
Expected: 帮助中列出 init/parse/template/facts/outline/body/fill/assemble/review/revise/run/status。

- [ ] **Step 6: Commit**

```bash
git add src/biaoshu_gen/cli.py tests/test_cli.py
git commit -m "feat: 分阶段 CLI 与断点续跑执行器"
```

---

### Task 11: extract_template 节点（harness）

**Files:**
- Create: `src/biaoshu_gen/prompts/extract_template.py`
- Create: `src/biaoshu_gen/nodes/extract_template.py`
- Modify: `src/biaoshu_gen/nodes/__init__.py`（登记真实节点）
- Test: `tests/test_node_extract_template.py`

**Interfaces:**
- Consumes: `HarnessTask`/`prepare_workspace`/`run_harness_task`（Task 7）、`run_dir`（Task 5）
- Produces: `extract_template_node(state) -> dict`，返回 `{"template_md_path": str, "template_report_path": str}`；产物在 `02_template/template.md` 与 `02_template/report.md`，工作区内有 `tender.md`（复制自 `01_parse/tender.md`）与可选 `标书模板.docx`

- [ ] **Step 1: 写失败测试（mock run_harness_task）**

```python
from pathlib import Path

from biaoshu_gen.nodes import extract_template as et
from biaoshu_gen.state import BidState, run_dir


def test_extract_template_node(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1", tender_path="t.docx")
    d = run_dir(state) / "01_parse"
    d.mkdir(parents=True)
    (d / "tender.md").write_text("# 招标公告", encoding="utf-8")
    tpl = tmp_path / "标书模板.docx"
    tpl.write_bytes(b"fake-docx")
    state = state.model_copy(update={"template_docx_path": str(tpl)})

    captured = {}

    def fake_run(task):
        captured["prompt"] = task.prompt
        captured["cwd"] = task.cwd
        for p in task.expected_outputs:
            p.write_text("内容", encoding="utf-8")
        return task.expected_outputs
    monkeypatch.setattr(et, "run_harness_task", fake_run)

    updates = et.extract_template_node(state)
    ws = run_dir(state) / "02_template"
    assert (ws / "tender.md").read_text(encoding="utf-8") == "# 招标公告"
    assert (ws / "标书模板.docx").exists()
    assert "template.md" in captured["prompt"]
    assert updates["template_md_path"] == str(ws / "template.md")
    assert updates["template_report_path"] == str(ws / "report.md")
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_node_extract_template.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 prompts/extract_template.py 与 nodes/extract_template.py**

`prompts/extract_template.py`:

```python
"""投标模板抽取节点 prompt（harness）。"""

SYSTEM = "你是投标文件结构分析师，负责拆解招标文件对响应文件（标书）的格式要求。"

TEMPLATE = """工作区说明：
- tender.md：招标文件全文（Markdown）
- {template_line}

任务：拆解招标文件要求的响应文件格式，产出两个文件：

1. template.md —— 响应文件模板：
   - 标书完整目录树（按招标文件要求的组成部分，如投标函、报价文件、货物一览表、
     资格证明文件、技术方案、偏离表、商务响应等）
   - 每个组成部分的填写要求（格式、签字盖章、附件材料）
   - 标注各部分属于"表格类填写"还是"文档类编写"
2. report.md —— 用户查阅报告：目录结构、各部分要求摘要、招标文件原文依据

要求：
- 只依据招标文件原文，不得虚构组成部分
- {template_note}
- 两个文件均为 UTF-8 编码，完成后必须存在且非空
"""


def build_user_prompt(has_template_docx: bool) -> str:
    if has_template_docx:
        template_line = "标书模板.docx：随招标文件提供的响应文件模板（参考用）"
        template_note = "对照 标书模板.docx 的结构，在 report.md 中说明模板与招标要求的对应关系"
    else:
        template_line = "（未提供响应文件模板 docx）"
        template_note = "没有模板 docx 时，完全依据招标文件文字要求构建目录树"
    return TEMPLATE.format(template_line=template_line, template_note=template_note)
```

`nodes/extract_template.py`:

```python
"""节点 2：投标模板抽取（harness：Claude Code SDK）。"""
from pathlib import Path

from ..harness import HarnessTask, prepare_workspace, run_harness_task
from ..prompts.extract_template import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def extract_template_node(state: BidState) -> dict:
    d = run_dir(state)
    inputs = [(d / "01_parse" / "tender.md", "tender.md")]
    if state.template_docx_path:
        inputs.append((Path(state.template_docx_path), "标书模板.docx"))
    ws = prepare_workspace(d, "02_template", inputs)
    template_md = ws / "template.md"
    report_md = ws / "report.md"
    run_harness_task(HarnessTask(
        prompt=SYSTEM + "\n\n" + build_user_prompt(bool(state.template_docx_path)),
        cwd=ws,
        expected_outputs=[template_md, report_md],
    ))
    return {"template_md_path": str(template_md), "template_report_path": str(report_md)}
```

`nodes/__init__.py` 登记处追加：

```python
from .extract_template import extract_template_node    # noqa: E402
DEFAULT_NODES["extract_template"] = extract_template_node
```

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_node_extract_template.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/prompts/extract_template.py src/biaoshu_gen/nodes tests/test_node_extract_template.py
git commit -m "feat: 投标模板抽取 harness 节点"
```

---

### Task 12: facts + outline 节点（人工控制点：用户编辑优先）

**Files:**
- Create: `src/biaoshu_gen/prompts/facts.py`、`src/biaoshu_gen/prompts/outline.py`
- Create: `src/biaoshu_gen/nodes/facts.py`、`src/biaoshu_gen/nodes/outline.py`
- Modify: `src/biaoshu_gen/nodes/__init__.py`（登记两个节点）
- Test: `tests/test_node_facts_outline.py`

**Interfaces:**
- Consumes: `make_agent`（Task 6）、schema 读写（Task 2）、`run_dir`（Task 5）
- Produces:
  - `facts_node(state) -> dict`：若 `03_facts.yaml` 已存在 → 直接读取返回（用户编辑优先，不调 LLM）；否则 LLM 生成并落盘。返回 `{"facts": GlobalFacts}`
  - `outline_node(state) -> dict`：同规则用 `04_outline.yaml`。返回 `{"outline: Outline}`
  - prompts: `facts.SYSTEM/build_user_prompt(metadata: str, scoring: str)`、`outline.SYSTEM/build_user_prompt(requirements: str, technical_rules: str, facts: str, template_md: str)`

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

from biaoshu_gen.nodes import facts as facts_mod
from biaoshu_gen.nodes import outline as outline_mod
from biaoshu_gen.schemas import GlobalFacts, Outline
from biaoshu_gen.state import BidState, run_dir


def _no_llu_factory():
    """任何调用都会炸的工厂——用于断言'已存在文件时不调 LLM'。"""
    def make(*a, **kw):
        raise AssertionError("不应调用 LLM")
    return make


def test_facts_existing_yaml_wins(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1")
    p = run_dir(state) / "03_facts.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("schedule: 90 天\nstaffing: 项目经理 1 名\n", encoding="utf-8")
    monkeypatch.setattr(facts_mod, "make_agent", _no_llu_factory())
    updates = facts_mod.facts_node(state)
    assert updates["facts"].schedule == "90 天"


def test_facts_generates_when_missing(tmp_path: Path, monkeypatch, fake_agent_factory):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1", metadata=None, scoring=None)
    monkeypatch.setattr(facts_mod, "make_agent",
                        fake_agent_factory({GlobalFacts: {"schedule": "60 天"}}))
    updates = facts_mod.facts_node(state)
    assert updates["facts"].schedule == "60 天"
    assert (run_dir(state) / "03_facts.yaml").exists()


def test_outline_existing_yaml_wins(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1")
    p = run_dir(state) / "04_outline.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("sections:\n- title: 总体方案\n  target_words: 800\ntotal_words: 800\n",
                 encoding="utf-8")
    monkeypatch.setattr(outline_mod, "make_agent", _no_llu_factory())
    updates = outline_mod.outline_node(state)
    assert updates["outline"].sections[0].title == "总体方案"


def test_outline_generates_with_template_context(tmp_path: Path, monkeypatch, fake_agent_factory):
    monkeypatch.chdir(tmp_path)
    tpl = tmp_path / "template.md"
    tpl.write_text("# 模板\n- 技术方案\n", encoding="utf-8")
    state = BidState(run_id="run-1", template_md_path=str(tpl))
    captured = {}

    def make(output_type, system_prompt, retries=2):
        from pydantic_ai import Agent
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        async def fn(messages, info: AgentInfo):
            captured["last_prompt"] = str(messages[-1].content)
            return {"sections": [{"title": "总体方案"}], "total_words": 500}
        return Agent(model=FunctionModel(fn), system_prompt=system_prompt, retries=retries)
    monkeypatch.setattr(outline_mod, "make_agent", make)

    updates = outline_mod.outline_node(state)
    assert updates["outline"].sections[0].title == "总体方案"
    assert "# 模板" in captured["last_prompt"]        # 模板上下文进入 prompt
    assert (run_dir(state) / "04_outline.yaml").exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_node_facts_outline.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 prompts 与 nodes**

`prompts/facts.py`:

```python
"""全局事实设定节点 prompt。"""

SYSTEM = "你是投标方案架构师，负责提炼全局事实设定，后续所有正文必须与之一致。"

TEMPLATE = """基于以下招标信息，提炼本次投标的全局事实设定：

【标书元数据】
{metadata}

【评标标准】
{scoring}

输出要求：
- schedule 工期设置：总工期与关键里程碑（必须满足交货日期要求）
- staffing 人员配置：关键角色与人数
- software_metrics 软件指标：对招标技术要求的逐条承诺（优于或等于要求）
- extra 其他全局事实（质保、培训、驻场等承诺）
"""


def build_user_prompt(metadata: str, scoring: str) -> str:
    return TEMPLATE.format(metadata=metadata or "（无）", scoring=scoring or "（无）")
```

`nodes/facts.py`:

```python
"""节点 3：全局事实设定（人工控制点 1：03_facts.yaml 用户编辑优先）。"""
from ..models import make_agent
from ..prompts.facts import SYSTEM, build_user_prompt
from ..schemas import GlobalFacts, from_yaml_file, to_yaml_file
from ..state import BidState, run_dir


def facts_node(state: BidState) -> dict:
    yaml_path = run_dir(state) / "03_facts.yaml"
    if yaml_path.exists():                       # 用户已编辑（或上游已产出）→ 不调 LLM
        return {"facts": from_yaml_file(GlobalFacts, yaml_path)}
    agent = make_agent(GlobalFacts, SYSTEM)
    result: GlobalFacts = agent.run_sync(build_user_prompt(
        metadata=state.metadata.model_dump_json(indent=2) if state.metadata else "",
        scoring=state.scoring.model_dump_json(indent=2) if state.scoring else "",
    )).output
    to_yaml_file(result, yaml_path)
    return {"facts": result}
```

`prompts/outline.py`:

```python
"""技术方案目录生成节点 prompt。"""

SYSTEM = "你是投标技术方案架构师，目录必须覆盖招标技术要求并响应技术评分标准。"

TEMPLATE = """为技术方案生成章节目录。

【标书需求】
{requirements}

【技术评分标准（逐条必须在目录中有所响应）】
{technical_rules}

【全局事实设定】
{facts}

【响应文件模板结构（目录须与之衔接）】
{template_md}

输出要求：
- sections：章节列表（title、target_words 预期字数、key_points 要点）
- 章节粒度适中（5~10 章），总字数符合投标常见体量（total_words 为各章之和）
"""


def build_user_prompt(requirements: str, technical_rules: str, facts: str, template_md: str) -> str:
    return TEMPLATE.format(
        requirements=requirements or "（无）",
        technical_rules=technical_rules or "（无）",
        facts=facts or "（无）",
        template_md=template_md or "（无）",
    )
```

`nodes/outline.py`:

```python
"""节点 4：技术方案目录生成（人工控制点 2：04_outline.yaml 用户编辑优先）。"""
from pathlib import Path

from ..models import make_agent
from ..prompts.outline import SYSTEM, build_user_prompt
from ..schemas import Outline, from_yaml_file, to_yaml_file
from ..state import BidState, run_dir


def outline_node(state: BidState) -> dict:
    yaml_path = run_dir(state) / "04_outline.yaml"
    if yaml_path.exists():
        return {"outline": from_yaml_file(Outline, yaml_path)}
    template_md = ""
    if state.template_md_path and Path(state.template_md_path).exists():
        template_md = Path(state.template_md_path).read_text(encoding="utf-8")
    agent = make_agent(Outline, SYSTEM)
    result: Outline = agent.run_sync(build_user_prompt(
        requirements=state.requirements.model_dump_json(indent=2) if state.requirements else "",
        technical_rules="\n".join(state.scoring.technical_rules) if state.scoring else "",
        facts=state.facts.model_dump_json(indent=2) if state.facts else "",
        template_md=template_md,
    )).output
    to_yaml_file(result, yaml_path)
    return {"outline": result}
```

`nodes/__init__.py` 登记处追加：

```python
from .facts import facts_node                          # noqa: E402
from .outline import outline_node                      # noqa: E402
DEFAULT_NODES["facts"] = facts_node
DEFAULT_NODES["outline"] = outline_node
```

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_node_facts_outline.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/prompts/facts.py src/biaoshu_gen/prompts/outline.py src/biaoshu_gen/nodes tests/test_node_facts_outline.py
git commit -m "feat: facts/outline 节点与用户编辑优先规则"
```

---

### Task 13: body + body_review 节点（技术方案生成内循环）

**Files:**
- Create: `src/biaoshu_gen/prompts/body.py`、`src/biaoshu_gen/prompts/body_review.py`
- Create: `src/biaoshu_gen/nodes/body.py`、`src/biaoshu_gen/nodes/body_review.py`
- Modify: `src/biaoshu_gen/nodes/__init__.py`（登记两个节点）
- Test: `tests/test_node_body.py`

**Interfaces:**
- Consumes: `make_agent`（Task 6）、`KnowledgeBase`/`count_chars`（Task 4）、`get_settings().word_tolerance`（Task 1）
- Produces:
  - `body_node(state) -> dict`：按 `state.outline.sections` 逐章生成，写 `05_body/{i:02d}-{安全文件名}.md` 与 `05_body/body.md`；返回 `{"body_md_path": str, "body_feedback": ""}`（消费回环意见后清空）
  - `body_review_node(state) -> dict`：代码侧 ±20% 字数校验 + LLM 一致性审核；写 `05_body/body_review_round_N.md`；返回 `{"body_review_passed": bool, "body_feedback": str, "body_review_rounds": int}`（rounds 每次 +1）
  - `nodes/body.py` 内私有 `_safe_name(title: str) -> str`（Windows 非法字符替换为 `-`，截断 40 字符）
  - 章节文件定位规则：`body_review` 用 `d.glob(f"{i:02d}-*.md")` 按序号定位，不依赖文件名拼写

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

from biaoshu_gen.nodes import body as body_mod
from biaoshu_gen.nodes import body_review as br_mod
from biaoshu_gen.schemas import BodyReviewReport, GlobalFacts, Outline, OutlineSection, SectionBody
from biaoshu_gen.state import BidState, run_dir


def _kb_dir(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    kb.mkdir(exist_ok=True)
    (kb / "简介.md").write_text("公司具备 CMMI5 与等保三级案例。", encoding="utf-8")
    return kb


def _state(tmp_path: Path) -> BidState:
    return BidState(
        run_id="run-1", kb_dir=str(_kb_dir(tmp_path)),
        facts=GlobalFacts(schedule="90 天", staffing="5 人"),
        outline=Outline(sections=[
            OutlineSection(title="总体方案", target_words=20, key_points=["架构"]),
            OutlineSection(title="实施方案", target_words=20, key_points=["进度"]),
        ], total_words=40),
    )


def test_body_writes_sections_and_md(tmp_path: Path, monkeypatch, fake_agent_factory):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(body_mod, "make_agent", fake_agent_factory(
        {SectionBody: {"title": "占位", "content": "本章内容围绕架构展开。"}}))
    updates = body_mod.body_node(state)
    d = run_dir(state) / "05_body"
    assert (d / "01-总体方案.md").exists() and (d / "02-实施方案.md").exists()
    body_md = (d / "body.md").read_text(encoding="utf-8")
    assert "# 占位" in body_md and "本章内容" in body_md
    assert updates["body_feedback"] == ""


def test_body_feedback_injected_into_prompt(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path).model_copy(update={"body_feedback": "补充实施计划"})
    captured = {}

    def make(output_type, system_prompt, retries=2):
        from pydantic_ai import Agent
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        async def fn(messages, info: AgentInfo):
            captured["prompts"] = captured.get("prompts", []) + [str(messages[-1].content)]
            return {"title": "占位", "content": "内容"}
        return Agent(model=FunctionModel(fn), system_prompt=system_prompt, retries=retries)
    monkeypatch.setattr(body_mod, "make_agent", make)

    body_mod.body_node(state)
    assert all("补充实施计划" in p for p in captured["prompts"])   # 回环意见进入每章 prompt


def _prepare_body(tmp_path: Path, monkeypatch, content: str) -> BidState:
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setattr(body_mod, "make_agent", fake_agent_factory(
        {SectionBody: {"title": "占位", "content": content}}))
    body_mod.body_node(state)
    return state


def test_body_review_word_violation_forces_fail(tmp_path: Path, monkeypatch, fake_agent_factory):
    state = _prepare_body(tmp_path, monkeypatch, content="太短")   # 远低于 20 字目标下限
    monkeypatch.setattr(br_mod, "make_agent", fake_agent_factory(
        {BodyReviewReport: {"passed": True, "issues": []}}))       # LLM 放行
    updates = br_mod.body_review_node(state)
    assert updates["body_review_passed"] is False                  # 代码侧字数校验否决
    assert any("字数不足" in i for i in updates["body_feedback"].split("；"))
    assert updates["body_review_rounds"] == 1
    assert (run_dir(state) / "05_body" / "body_review_round_1.md").exists()


def test_body_review_pass(tmp_path: Path, monkeypatch, fake_agent_factory):
    content = "方案内容" * 12            # 48 字 > 20*(1+0.2) 上限内? 20*1.2=24, 48 超上限 → 用 20 字目标匹配
    state = _prepare_body(tmp_path, monkeypatch, content="字数合适的内容。" * 3)
    monkeypatch.setattr(br_mod, "make_agent", fake_agent_factory(
        {BodyReviewReport: {"passed": True, "issues": []}}))
    updates = br_mod.body_review_node(state)
    assert updates["body_review_passed"] is True
```

注：第 4 个用例中每章实际字数需落在 `target_words ±20%`（20 字目标 → 16~24 字）。`"字数合适的内容。"*3` = 24 字（含标点计数），在上限内。若实现后计数不符，调整 content 使其落在区间——测试意图是"字数达标 + LLM 通过 → passed"。

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_node_body.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 prompts 与 nodes**

`prompts/body.py`:

```python
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
```

`nodes/body.py`:

```python
"""节点 5：逐章生成技术方案正文。"""
import re
from pathlib import Path

from ..kb import KnowledgeBase
from ..models import make_agent
from ..prompts.body import SYSTEM, build_user_prompt
from ..schemas import SectionBody
from ..state import BidState, run_dir


def _safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "-", title).strip("-")[:40] or "section"


def body_node(state: BidState) -> dict:
    assert state.outline, "outline 未生成，无法撰写正文"
    d = run_dir(state) / "05_body"
    d.mkdir(parents=True, exist_ok=True)
    kb = KnowledgeBase.load(Path(state.kb_dir))
    facts_text = state.facts.model_dump_json(indent=2) if state.facts else ""
    agent = make_agent(SectionBody, SYSTEM)
    parts: list[str] = []
    for i, sec in enumerate(state.outline.sections, 1):
        snippets = kb.search(sec.title + " " + " ".join(sec.key_points))
        kb_text = "\n\n".join(f"【{c.source.name}】\n{c.text}" for c in snippets) or "（无）"
        result: SectionBody = agent.run_sync(build_user_prompt(
            title=sec.title, target_words=sec.target_words, key_points=sec.key_points,
            facts=facts_text, kb=kb_text, feedback=state.body_feedback,
        )).output
        (d / f"{i:02d}-{_safe_name(sec.title)}.md").write_text(result.content, encoding="utf-8")
        parts.append(f"# {result.title}\n\n{result.content}")
    body_md = d / "body.md"
    body_md.write_text("\n\n".join(parts), encoding="utf-8")
    return {"body_md_path": str(body_md), "body_feedback": ""}
```

`prompts/body_review.py`:

```python
"""正文审核检验节点 prompt。"""

SYSTEM = "你是投标文件审核专家，负责技术方案正文的一致性与合规性检验。"

TEMPLATE = """审核以下技术方案正文。

【全局事实设定】
{facts}

【废标项+扣分项（正文必须响应且不得触犯）】
{invalidation}

【各章节字数统计（代码已统计，容差 ±20%，超差已由代码标记）】
{word_table}

检查内容：
1. 与全局事实设定的一致性（工期/人员/指标承诺是否一致）
2. 事实性偏差（是否出现与招标需求矛盾的内容）
3. 废标项与扣分项是否已响应

正文内容：

{body}
"""


def build_user_prompt(facts: str, invalidation: str, word_table: str, body: str) -> str:
    return TEMPLATE.format(facts=facts or "（无）", invalidation=invalidation or "（无）",
                           word_table=word_table, body=body)
```

`nodes/body_review.py`:

```python
"""节点 6：正文审核检验（一致性/事实/废标扣分/字数 ±20%）。"""
from pathlib import Path

from ..config import get_settings
from ..kb import count_chars
from ..models import make_agent
from ..prompts.body_review import SYSTEM, build_user_prompt
from ..schemas import BodyReviewReport
from ..state import BidState, run_dir


def body_review_node(state: BidState) -> dict:
    assert state.outline and state.body_md_path, "body 未生成"
    d = run_dir(state) / "05_body"
    tolerance = get_settings().word_tolerance

    rows: list[str] = []
    word_issues: list[str] = []
    for i, sec in enumerate(state.outline.sections, 1):
        matches = sorted(d.glob(f"{i:02d}-*.md"))
        assert matches, f"章节文件缺失: {d}/{i:02d}-*.md"
        actual = count_chars(matches[0].read_text(encoding="utf-8"))
        rows.append(f"- 《{sec.title}》 目标 {sec.target_words} 字 / 实际 {actual} 字")
        if actual < sec.target_words * (1 - tolerance):
            word_issues.append(f"章节《{sec.title}》字数不足：目标约 {sec.target_words}，实际 {actual}")
        elif actual > sec.target_words * (1 + tolerance):
            word_issues.append(f"章节《{sec.title}》字数超出：目标约 {sec.target_words}，实际 {actual}")

    invalidation_text = ""
    if state.invalidation:
        invalidation_text = "\n".join(
            f"[{it.kind}] {it.requirement}（依据：{it.source_quote}）"
            for it in state.invalidation.items)

    body = Path(state.body_md_path).read_text(encoding="utf-8")
    agent = make_agent(BodyReviewReport, SYSTEM)
    report: BodyReviewReport = agent.run_sync(build_user_prompt(
        facts=state.facts.model_dump_json(indent=2) if state.facts else "",
        invalidation=invalidation_text,
        word_table="\n".join(rows),
        body=body,
    )).output

    issues = list(report.issues) + word_issues
    passed = report.passed and not word_issues
    rounds = state.body_review_rounds + 1
    report_path = d / f"body_review_round_{rounds}.md"
    report_path.write_text(
        f"# 正文审核 第 {rounds} 轮\n\n结论：{'通过' if passed else '不通过'}\n\n"
        "## 问题清单\n" + ("\n".join(f"- {i}" for i in issues) or "- 无"),
        encoding="utf-8",
    )
    return {
        "body_review_passed": passed,
        "body_feedback": "；".join(issues),
        "body_review_rounds": rounds,
    }
```

（实现时把 `open(...)` 换成 `Path(state.body_md_path).read_text(encoding="utf-8")`，与项目风格一致。）

`nodes/__init__.py` 登记处追加：

```python
from .body import body_node                            # noqa: E402
from .body_review import body_review_node              # noqa: E402
DEFAULT_NODES["body"] = body_node
DEFAULT_NODES["body_review"] = body_review_node
```

（上面 `body_review.py` 代码块中 `body` 的读取已直接使用 `Path(...).read_text(...)`。）

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_node_body.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/prompts/body.py src/biaoshu_gen/prompts/body_review.py src/biaoshu_gen/nodes tests/test_node_body.py
git commit -m "feat: 技术方案正文生成与审核检验节点"
```

---

### Task 14: fill_forms / deviation_table / commercial 节点（harness × 3，并行）

**Files:**
- Modify: `src/biaoshu_gen/kb.py`（增加 `KnowledgeBase.dump_summary`）
- Modify: `src/biaoshu_gen/harness.py`（增加 `prepare_agent_workspace`）
- Create: `src/biaoshu_gen/prompts/fill_forms.py`、`prompts/deviation_table.py`、`prompts/commercial.py`
- Create: `src/biaoshu_gen/nodes/fill_forms.py`、`nodes/deviation_table.py`、`nodes/commercial.py`
- Modify: `src/biaoshu_gen/nodes/__init__.py`（登记三个节点）
- Test: `tests/test_node_fill.py`

**Interfaces:**
- Consumes: `HarnessTask`/`prepare_workspace`/`run_harness_task`（Task 7）、`KnowledgeBase`（Task 4）、`run_dir`（Task 5）
- Produces:
  - `KnowledgeBase.dump_summary(path: Path) -> Path`：写 harness 可读摘要（文本块 + 图片绝对路径清单）
  - `harness.prepare_agent_workspace(state: BidState, subdir: str, extra_inputs: list[tuple[Path, str]] | None) -> Path`：标准 harness 工作区——基础输入 `tender.md`、`invalidation.yaml`、可选 `标书模板.docx` + 调用方附加输入 + 生成 `kb.md`（Task 16 的 review/revise 也复用）
  - `fill_forms_node(state) -> {"forms_docx_path": str}`，产物 `06_fill/forms/forms.docx`
  - `deviation_table_node(state) -> {"deviation_docx_path": str}`，产物 `06_fill/deviation/deviation.docx`
  - `commercial_node(state) -> {"commercial_docx_path": str}`，产物 `06_fill/commercial/commercial.docx`
  - 三个工作区按子目录隔离（三节点在 LangGraph 同一 superstep 并行执行，互不干扰）
  - prompts: 每个模块 `SYSTEM` + `build_user_prompt(output: str) -> str`

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

from biaoshu_gen.harness import prepare_agent_workspace
from biaoshu_gen.kb import KnowledgeBase
from biaoshu_gen.nodes import commercial as com
from biaoshu_gen.nodes import deviation_table as dev
from biaoshu_gen.nodes import fill_forms as ff
from biaoshu_gen.state import BidState, run_dir


def _fake_run(captured):
    def fake(task):
        captured.append((task.cwd, task.prompt, task.expected_outputs))
        for p in task.expected_outputs:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"fake-docx")
        return task.expected_outputs
    return fake


def _base_state(tmp_path: Path, monkeypatch) -> BidState:
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1", kb_dir=str(tmp_path / "kb"))
    (tmp_path / "kb").mkdir(exist_ok=True)
    (tmp_path / "kb" / "简介.md").write_text("公司具备 CMMI5。", encoding="utf-8")
    (tmp_path / "kb" / "营业执照.jpg").write_bytes(b"\xff\xd8img")
    parse = run_dir(state) / "01_parse"
    parse.mkdir(parents=True)
    (parse / "tender.md").write_text("# 招标公告", encoding="utf-8")
    (parse / "invalidation.yaml").write_text("items: []\n", encoding="utf-8")
    (parse / "metadata.yaml").write_text("project_name: 演示\n", encoding="utf-8")
    (parse / "requirements.yaml").write_text("tech_requirements: []\n", encoding="utf-8")
    (parse / "scoring.yaml").write_text("technical_rules: []\n", encoding="utf-8")
    (run_dir(state) / "03_facts.yaml").write_text("schedule: 90 天\n", encoding="utf-8")
    return state


def test_dump_summary_contains_text_and_images(tmp_path: Path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "a.md").write_text("具备 ISO27001。", encoding="utf-8")
    (kb_dir / "lic.jpg").write_bytes(b"\xff\xd8x")
    out = KnowledgeBase.load(kb_dir).dump_summary(tmp_path / "kb.md")
    text = out.read_text(encoding="utf-8")
    assert "ISO27001" in text and str((kb_dir / "lic.jpg").resolve()) in text


def test_three_fill_nodes_isolated_workspaces(tmp_path: Path, monkeypatch):
    state = _base_state(tmp_path, monkeypatch)
    captured = []
    for mod in (ff, dev, com):
        monkeypatch.setattr(mod, "run_harness_task", _fake_run(captured))
    u1 = ff.fill_forms_node(state)
    u2 = dev.deviation_table_node(state)
    u3 = com.commercial_node(state)

    assert u1["forms_docx_path"].endswith(str(Path("06_fill/forms/forms.docx")))
    assert u2["deviation_docx_path"].endswith("deviation.docx")
    assert u3["commercial_docx_path"].endswith("commercial.docx")
    cwds = [str(c[0]) for c in captured]
    assert len({c[0] for c in captured}) == 3            # 工作区互相隔离
    # 标准工作区内容：tender.md / invalidation.yaml / kb.md
    ws = run_dir(state) / "06_fill" / "forms"
    assert (ws / "tender.md").exists() and (ws / "kb.md").exists()
    assert "CMMI5" in (ws / "kb.md").read_text(encoding="utf-8")
    # 各节点附加输入正确
    assert (ws / "metadata.yaml").exists()
    assert (run_dir(state) / "06_fill" / "deviation" / "scoring.yaml").exists()
    assert (run_dir(state) / "06_fill" / "deviation" / "facts.yaml").exists()


def test_prepare_agent_workspace_base_inputs(tmp_path: Path, monkeypatch):
    state = _base_state(tmp_path, monkeypatch)
    tpl = tmp_path / "标书模板.docx"
    tpl.write_bytes(b"tpl")
    state = state.model_copy(update={"template_docx_path": str(tpl)})
    ws = prepare_agent_workspace(state, "06_fill/forms", [
        (tmp_path / "extra.yaml", "extra.yaml")])
    (tmp_path / "extra.yaml").write_text("e: 1", encoding="utf-8")
    ws = prepare_agent_workspace(state, "06_fill/forms", [
        (tmp_path / "extra.yaml", "extra.yaml")])
    for name in ("tender.md", "invalidation.yaml", "标书模板.docx", "kb.md", "extra.yaml"):
        assert (ws / name).exists(), name
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_node_fill.py -v`
Expected: FAIL（dump_summary / prepare_agent_workspace / 节点不存在）

- [ ] **Step 3: 实现 kb.dump_summary、harness.prepare_agent_workspace、三个 prompt 与节点**

`kb.py` 的 `KnowledgeBase` 类内追加方法：

```python
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
```

`harness.py` 末尾追加：

```python
def prepare_agent_workspace(state, subdir: str,
                            extra_inputs: list[tuple[Path, Path | str]] | None = None) -> Path:
    """填充/审核类 harness 节点的标准工作区：
    基础输入 tender.md + invalidation.yaml + 可选 标书模板.docx，附加调用方输入，并生成 kb.md。"""
    from .kb import KnowledgeBase
    from .state import run_dir

    parse = run_dir(state) / "01_parse"
    inputs = [(parse / "tender.md", "tender.md"),
              (parse / "invalidation.yaml", "invalidation.yaml")]
    if state.template_docx_path:
        inputs.append((Path(state.template_docx_path), "标书模板.docx"))
    inputs.extend([(Path(p), n) for p, n in (extra_inputs or [])])
    ws = prepare_workspace(run_dir(state), subdir, inputs)
    KnowledgeBase.load(Path(state.kb_dir)).dump_summary(ws / "kb.md")
    return ws
```

`prompts/fill_forms.py`:

```python
"""投标函+报价文件+货物一览表+资格证明文件填写 prompt（harness）。"""

SYSTEM = "你是投标文件填写专员，负责严格按招标文件要求填写表格类投标文件。"

TEMPLATE = """工作区文件：
- tender.md：招标文件全文；invalidation.yaml：废标项+扣分项
- metadata.yaml：标书元数据；kb.md：企业知识库摘要（含营业执照等图片绝对路径）
- 标书模板.docx：响应文件模板（若有）

任务：用 python-docx 创建表格类填写文件 {output}，包含：
1. 投标函：格式按招标文件要求，含项目名称/编号/投标有效期；报价数字一律写"〔待人工填写〕"
2. 报价文件/报价一览表：结构齐全，金额单元格写"〔待人工填写〕"
3. 货物一览表：按招标采购清单与 metadata 逐项列出
4. 资格证明文件：引用 kb.md 中的资质与图片材料路径（如营业执照）

要求：
- 逐条核对 invalidation.yaml：签字/盖章/附件/格式要求必须满足或预留位置
- 表格规范、单元格可编辑；完成后文件必须存在且非空
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.format(output=output)
```

`prompts/deviation_table.py`:

```python
"""偏离表填写 prompt（harness）。"""

SYSTEM = "你是投标文件填写专员，负责编制投标偏离表。"

TEMPLATE = """工作区文件：
- tender.md：招标文件全文；requirements.yaml：标书需求；scoring.yaml：评分标准
- invalidation.yaml：废标项+扣分项；facts.yaml：全局事实设定；kb.md：企业知识库摘要

任务：用 python-docx 创建偏离表 {output}：
- 表格列：序号 / 招标要求 / 投标响应 / 偏离说明（正偏离或无偏离）
- 逐条覆盖 requirements.yaml 中的技术要求、实施要求与商务参数（含交货日期/质保期）
- 投标响应必须与 facts.yaml 的承诺一致；严禁出现负偏离
- invalidation.yaml 中被扣分评分的条目必须逐条入表

完成后文件必须存在且非空。
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.format(output=output)
```

`prompts/commercial.py`:

```python
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
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.format(output=output)
```

`nodes/fill_forms.py`:

```python
"""节点 7：投标函+报价文件+货物一览表+资格证明文件（harness 填表）。"""
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.fill_forms import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def fill_forms_node(state: BidState) -> dict:
    ws = prepare_agent_workspace(state, "06_fill/forms", [
        (run_dir(state) / "01_parse" / "metadata.yaml", "metadata.yaml")])
    out = ws / "forms.docx"
    run_harness_task(HarnessTask(prompt=SYSTEM + "\n\n" + build_user_prompt(str(out)),
                                 cwd=ws, expected_outputs=[out]))
    return {"forms_docx_path": str(out)}
```

`nodes/deviation_table.py`:

```python
"""节点 8：偏离表（harness 填表）。"""
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.deviation_table import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def deviation_table_node(state: BidState) -> dict:
    ws = prepare_agent_workspace(state, "06_fill/deviation", [
        (run_dir(state) / "01_parse" / "requirements.yaml", "requirements.yaml"),
        (run_dir(state) / "01_parse" / "scoring.yaml", "scoring.yaml"),
        (run_dir(state) / "03_facts.yaml", "facts.yaml")])
    out = ws / "deviation.docx"
    run_harness_task(HarnessTask(prompt=SYSTEM + "\n\n" + build_user_prompt(str(out)),
                                 cwd=ws, expected_outputs=[out]))
    return {"deviation_docx_path": str(out)}
```

`nodes/commercial.py`:

```python
"""节点 9：商务响应文件（harness 填表）。"""
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.commercial import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def commercial_node(state: BidState) -> dict:
    ws = prepare_agent_workspace(state, "06_fill/commercial", [
        (run_dir(state) / "01_parse" / "scoring.yaml", "scoring.yaml"),
        (run_dir(state) / "01_parse" / "metadata.yaml", "metadata.yaml"),
        (run_dir(state) / "03_facts.yaml", "facts.yaml")])
    out = ws / "commercial.docx"
    run_harness_task(HarnessTask(prompt=SYSTEM + "\n\n" + build_user_prompt(str(out)),
                                 cwd=ws, expected_outputs=[out]))
    return {"commercial_docx_path": str(out)}
```

`nodes/__init__.py` 登记处追加：

```python
from .fill_forms import fill_forms_node                  # noqa: E402
from .deviation_table import deviation_table_node        # noqa: E402
from .commercial import commercial_node                  # noqa: E402
DEFAULT_NODES["fill_forms"] = fill_forms_node
DEFAULT_NODES["deviation_table"] = deviation_table_node
DEFAULT_NODES["commercial"] = commercial_node
```

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_node_fill.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen tests/test_node_fill.py
git commit -m "feat: 三填充 harness 节点与标准工作区"
```

---

### Task 15: assemble 节点（标书草稿拼装，纯代码）

**Files:**
- Create: `src/biaoshu_gen/nodes/assemble.py`
- Modify: `src/biaoshu_gen/nodes/__init__.py`
- Test: `tests/test_node_assemble.py`

**Interfaces:**
- Consumes: `copy_docx`/`markdown_to_docx`/`append_docx`（Task 3）、`run_dir`（Task 5）、state 中 `body_md_path` / `forms_docx_path` / `deviation_docx_path` / `commercial_docx_path` / `template_docx_path` / `draft_version` / `metadata`
- Produces: `assemble_node(state) -> dict`：产物 `07_draft/标书草稿_vN.docx`（N=draft_version+1）与 `07_draft/标书草稿_vN.md`，写 `07_draft/latest.txt`；返回 `{"draft_docx_path", "draft_md_path", "draft_version": N}`。拼装规则：有模板→复制模板为底稿；无模板→新建并加《{项目名} 投标文件》主标题；然后分页追加「# 技术方案」（body.md）与三个填充 docx 的全部内容

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

from docx import Document

from biaoshu_gen.nodes import assemble as asm
from biaoshu_gen.schemas import TenderMetadata
from biaoshu_gen.state import BidState, run_dir


def _make_docx(path: Path, text: str, with_table: bool = False) -> None:
    d = Document()
    d.add_heading(text, level=1)
    if with_table:
        t = d.add_table(rows=1, cols=2)
        t.cell(0, 0).text = "名称"
        t.cell(0, 1).text = "数量"
    d.save(path)


def _state(tmp_path: Path, monkeypatch, version: int = 0) -> BidState:
    monkeypatch.chdir(tmp_path)
    d = run_dir(BidState(run_id="run-1"))
    body = d / "05_body"
    body.mkdir(parents=True, exist_ok=True)
    (body / "body.md").write_text("# 总体方案\n\n本章内容。", encoding="utf-8")
    for name in ("forms", "deviation", "commercial"):
        p = d / "06_fill" / name / f"{name}.docx"
        p.parent.mkdir(parents=True, exist_ok=True)
        _make_docx(p, name, with_table=(name == "forms"))
    return BidState(
        run_id="run-1",
        metadata=TenderMetadata(project_name="演示项目"),
        body_md_path=str(body / "body.md"),
        forms_docx_path=str(d / "06_fill/forms/forms.docx"),
        deviation_docx_path=str(d / "06_fill/deviation/deviation.docx"),
        commercial_docx_path=str(d / "06_fill/commercial/commercial.docx"),
        draft_version=version,
    )


def test_assemble_no_template(tmp_path: Path, monkeypatch):
    state = _state(tmp_path, monkeypatch)
    updates = asm.assemble_node(state)
    dest = Path(updates["draft_docx_path"])
    assert dest.name == "标书草稿_v1.docx" and dest.exists()
    assert (run_dir(state) / "07_draft" / "latest.txt").read_text(encoding="utf-8") == "1"
    doc = Document(str(dest))
    texts = "\n".join(p.text for p in doc.paragraphs)
    assert "演示项目 投标文件" in texts and "总体方案" in texts and "forms" in texts
    assert len(doc.tables) == 1                     # forms.docx 的表格并入
    assert updates["draft_version"] == 1


def test_assemble_version_increments(tmp_path: Path, monkeypatch):
    state = _state(tmp_path, monkeypatch, version=1)
    updates = asm.assemble_node(state)
    assert Path(updates["draft_docx_path"]).name == "标书草稿_v2.docx"
    assert (run_dir(state) / "07_draft" / "latest.txt").read_text(encoding="utf-8") == "2"


def test_assemble_with_template_base(tmp_path: Path, monkeypatch):
    tpl = tmp_path / "标书模板.docx"
    _make_docx(tpl, "模板标题页")
    state = _state(tmp_path, monkeypatch).model_copy(update={"template_docx_path": str(tpl)})
    updates = asm.assemble_node(state)
    doc = Document(updates["draft_docx_path"])
    texts = "\n".join(p.text for p in doc.paragraphs)
    assert "模板标题页" in texts and "总体方案" in texts
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_node_assemble.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 nodes/assemble.py**

```python
"""节点 10：拼装标书草稿 docx（纯代码，无 LLM）。"""
from pathlib import Path

from docx import Document

from ..docx_io import append_docx, copy_docx, markdown_to_docx
from ..state import BidState, run_dir


def assemble_node(state: BidState) -> dict:
    out_dir = run_dir(state) / "07_draft"
    out_dir.mkdir(parents=True, exist_ok=True)
    version = state.draft_version + 1
    dest = out_dir / f"标书草稿_v{version}.docx"

    if state.template_docx_path and Path(state.template_docx_path).exists():
        doc = copy_docx(Path(state.template_docx_path), dest)     # 模板为底稿
    else:
        doc = Document()
        if state.metadata and state.metadata.project_name:
            doc.add_heading(f"{state.metadata.project_name} 投标文件", level=0)

    body_md = Path(state.body_md_path).read_text(encoding="utf-8")
    doc.add_page_break()
    markdown_to_docx(doc, "# 技术方案\n\n" + body_md)
    for p in (state.forms_docx_path, state.deviation_docx_path, state.commercial_docx_path):
        if p and Path(p).exists():
            doc.add_page_break()
            append_docx(doc, Path(p))
    doc.save(str(dest))

    (out_dir / "latest.txt").write_text(str(version), encoding="utf-8")
    md_path = out_dir / f"标书草稿_v{version}.md"
    md_path.write_text(body_md + "\n\n（已并入填充产物：forms / deviation / commercial docx）\n",
                       encoding="utf-8")
    return {"draft_docx_path": str(dest), "draft_md_path": str(md_path), "draft_version": version}
```

`nodes/__init__.py` 登记处追加：

```python
from .assemble import assemble_node                    # noqa: E402
DEFAULT_NODES["assemble"] = assemble_node
```

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_node_assemble.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/nodes tests/test_node_assemble.py
git commit -m "feat: 标书草稿拼装节点"
```

---

### Task 16: review + revise 节点（harness 审核与修改循环）

**Files:**
- Create: `src/biaoshu_gen/prompts/review.py`、`prompts/revise.py`
- Create: `src/biaoshu_gen/nodes/review.py`、`nodes/revise.py`
- Modify: `src/biaoshu_gen/nodes/__init__.py`
- Test: `tests/test_node_review.py`

**Interfaces:**
- Consumes: `prepare_agent_workspace`/`HarnessTask`/`run_harness_task`（Task 14/7）、`get_settings().revise_max_rounds`（Task 1）
- Produces:
  - `review_node(state) -> {"review_passed": bool, "review_report_path": str}`：产物 `08_review/review_round_{revision_round+1}.md`；VERDICT 行解析（`_parse_verdict`：倒序找 `VERDICT:` 行；找不到→保守 FAIL）；当 `verdict==FAIL 且 state.revision_round >= revise_max_rounds` 时向报告追加「## 需人工处理」段（路由已到 END，人工接管）
  - `revise_node(state) -> {"draft_docx_path", "draft_version": N+1, "revision_round": +1, ("draft_md_path": 新md 若产出)}`：工作区 `07_draft`，产物 `标书草稿_v{draft_version+1}.docx`，更新 `latest.txt`
  - prompts: `review.SYSTEM/build_user_prompt(output)`、`revise.SYSTEM/build_user_prompt(output, version)`

- [ ] **Step 1: 写失败测试**

```python
from pathlib import Path

from docx import Document

from biaoshu_gen.nodes import review as rv
from biaoshu_gen.nodes import revise as rs
from biaoshu_gen.state import BidState, run_dir


def _setup(tmp_path: Path, monkeypatch) -> BidState:
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1")
    d = run_dir(state)
    parse = d / "01_parse"
    parse.mkdir(parents=True)
    (parse / "tender.md").write_text("# 招标", encoding="utf-8")
    (parse / "invalidation.yaml").write_text("items: []\n", encoding="utf-8")
    (parse / "scoring.yaml").write_text("technical_rules: []\n", encoding="utf-8")
    (d / "03_facts.yaml").write_text("schedule: 90 天\n", encoding="utf-8")
    draft = d / "07_draft" / "标书草稿_v1.docx"
    draft.parent.mkdir(parents=True)
    Document().save(draft)
    (d / "07_draft" / "标书草稿_v1.md").write_text("# 正文", encoding="utf-8")
    return state.model_copy(update={
        "draft_docx_path": str(draft),
        "draft_md_path": str(d / "07_draft" / "标书草稿_v1.md"),
        "draft_version": 1,
    })


def _fake_harness(report_text: str, produced: Path):
    def fake(task):
        produced.parent.mkdir(parents=True, exist_ok=True)
        produced.write_text(report_text, encoding="utf-8")
        return task.expected_outputs
    return fake


def test_review_parses_verdict_pass(tmp_path: Path, monkeypatch):
    state = _setup(tmp_path, monkeypatch)
    out = run_dir(state) / "08_review" / "review_round_1.md"
    monkeypatch.setattr(rv, "run_harness_task", _fake_harness(
        "## 检查\n- 各项通过\n\nVERDICT: PASS", out))
    updates = rv.review_node(state)
    assert updates["review_passed"] is True
    assert "需人工处理" not in out.read_text(encoding="utf-8")


def test_review_fail_missing_verdict_treated_as_fail(tmp_path: Path, monkeypatch):
    state = _setup(tmp_path, monkeypatch)
    out = run_dir(state) / "08_review" / "review_round_1.md"
    monkeypatch.setattr(rv, "run_harness_task", _fake_harness("没有结论行", out))
    updates = rv.review_node(state)
    assert updates["review_passed"] is False


def test_review_fail_at_cap_appends_manual_note(tmp_path: Path, monkeypatch):
    state = _setup(tmp_path, monkeypatch).model_copy(update={"revision_round": 2})
    out = run_dir(state) / "08_review" / "review_round_3.md"
    monkeypatch.setattr(rv, "run_harness_task", _fake_harness(
        "- 问题A\n\nVERDICT: FAIL", out))
    updates = rv.review_node(state)
    assert updates["review_passed"] is False
    assert "需人工处理" in out.read_text(encoding="utf-8")


def test_review_fail_below_cap_no_manual_note(tmp_path: Path, monkeypatch):
    state = _setup(tmp_path, monkeypatch).model_copy(update={"revision_round": 0})
    out = run_dir(state) / "08_review" / "review_round_1.md"
    monkeypatch.setattr(rv, "run_harness_task", _fake_harness("VERDICT: FAIL", out))
    rv.review_node(state)
    assert "需人工处理" not in out.read_text(encoding="utf-8")


def test_revise_produces_next_version(tmp_path: Path, monkeypatch):
    state = _setup(tmp_path, monkeypatch).model_copy(update={
        "review_report_path": str(run_dir(state) / "08_review" / "review_round_1.md")})
    (run_dir(state) / "08_review").mkdir(parents=True, exist_ok=True)
    (run_dir(state) / "08_review" / "review_round_1.md").write_text(
        "VERDICT: FAIL\n- 补充质保承诺", encoding="utf-8")
    out = run_dir(state) / "07_draft" / "标书草稿_v2.docx"

    def fake(task):
        out.write_bytes(b"fake-docx")
        return task.expected_outputs
    monkeypatch.setattr(rs, "run_harness_task", fake)

    updates = rs.revise_node(state)
    assert updates["draft_version"] == 2 and updates["revision_round"] == 1
    assert updates["draft_docx_path"] == str(out)
    assert (run_dir(state) / "07_draft" / "latest.txt").read_text(encoding="utf-8") == "2"
```

- [ ] **Step 2: 运行确认失败**

Run: `poetry run pytest tests/test_node_review.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 prompts 与 nodes**

`prompts/review.py`:

```python
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
"""


def build_user_prompt(output: str) -> str:
    return TEMPLATE.format(output=output)
```

`prompts/revise.py`:

```python
"""按审核意见修改草稿 prompt（harness）。"""

SYSTEM = "你是投标文件修订专员，按审核意见最小化修改标书草稿。"

TEMPLATE = """工作区文件：
- {current}：当前标书草稿 docx
- review_report.md：审核意见（五方面问题清单）
- tender.md / invalidation.yaml / facts.yaml / kb.md / 标书模板.docx：依据材料

任务：按审核意见逐条修改草稿，产出新版本 {output}：
- 只修复意见指出的问题，保留既有正确内容
- 修改不得违反 facts.yaml，不得触犯废标项
- 用 python-docx 读取当前草稿、修改后另存为新文件（禁止覆盖原文件）
- 若正文内容变化，同步产出 {md_output}（Markdown 摘要，可选）

完成后 {output} 必须存在且非空。
"""


def build_user_prompt(output: str, version: int, current: str = "") -> str:
    current = current or f"标书草稿_v{max(version - 1, 1)}.docx"
    md_output = output.replace(".docx", ".md")
    return TEMPLATE.format(current=current, output=output, md_output=md_output)
```

`nodes/review.py`:

```python
"""节点 11：Agent 全面审核（harness），VERDICT 结论解析。"""
from pathlib import Path

from ..config import get_settings
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.review import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def _parse_verdict(report: Path) -> str:
    for line in reversed(report.read_text(encoding="utf-8").splitlines()):
        stripped = line.strip().upper()
        if stripped.startswith("VERDICT:"):
            return "PASS" if "PASS" in stripped else "FAIL"
    return "FAIL"                                   # 未找到结论 → 保守判 FAIL


def review_node(state: BidState) -> dict:
    d = run_dir(state)
    ws = prepare_agent_workspace(state, "08_review", [
        (Path(state.draft_docx_path), "标书草稿.docx"),
        (Path(state.draft_md_path), "标书草稿.md"),
        (d / "01_parse" / "scoring.yaml", "scoring.yaml"),
        (d / "03_facts.yaml", "facts.yaml"),
    ])
    n = state.revision_round + 1
    out = ws / f"review_round_{n}.md"
    run_harness_task(HarnessTask(prompt=SYSTEM + "\n\n" + build_user_prompt(str(out)),
                                 cwd=ws, expected_outputs=[out]))
    verdict = _parse_verdict(out)
    if verdict == "FAIL" and state.revision_round >= get_settings().revise_max_rounds:
        with out.open("a", encoding="utf-8") as f:      # 路由将到 END → 人工接管
            f.write("\n\n## 需人工处理\n\n已达到修改轮次上限，遗留问题需人工处理（人工审核签字环节）。\n")
    return {"review_passed": verdict == "PASS", "review_report_path": str(out)}
```

`nodes/revise.py`:

```python
"""节点 12：按审核意见修改草稿（harness），版本号管理。"""
from pathlib import Path

from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.revise import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def revise_node(state: BidState) -> dict:
    d = run_dir(state)
    n = state.draft_version + 1
    ws = prepare_agent_workspace(state, "07_draft", [
        (Path(state.draft_docx_path), Path(state.draft_docx_path).name),
        (Path(state.review_report_path), "review_report.md"),
        (d / "03_facts.yaml", "facts.yaml"),
    ])
    out = ws / f"标书草稿_v{n}.docx"
    run_harness_task(HarnessTask(
        prompt=SYSTEM + "\n\n" + build_user_prompt(
            str(out), n, current=Path(state.draft_docx_path).name),
        cwd=ws, expected_outputs=[out]))
    (ws / "latest.txt").write_text(str(n), encoding="utf-8")
    updates: dict = {
        "draft_docx_path": str(out),
        "draft_version": n,
        "revision_round": state.revision_round + 1,
    }
    md_out = ws / f"标书草稿_v{n}.md"
    if md_out.exists():
        updates["draft_md_path"] = str(md_out)
    return updates
```

`nodes/__init__.py` 登记处追加：

```python
from .review import review_node                        # noqa: E402
from .revise import revise_node                        # noqa: E402
DEFAULT_NODES["review"] = review_node
DEFAULT_NODES["revise"] = revise_node
```

- [ ] **Step 4: 运行测试通过**

Run: `poetry run pytest tests/test_node_review.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/prompts/review.py src/biaoshu_gen/prompts/revise.py src/biaoshu_gen/nodes tests/test_node_review.py
git commit -m "feat: 审核/修改 harness 节点与循环收敛"
```

---

### Task 17: 集成收尾 —— 全节点注册校验、README、端到端冒烟

**Files:**
- Modify: `README.md`（完整重写）
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 全部 12 个真实节点注册（无 stub）；README 使用文档；端到端冒烟通过

- [ ] **Step 1: 写失败测试（注册完整性）**

```python
from biaoshu_gen.nodes import DEFAULT_NODES, NODE_NAMES


def test_all_nodes_registered_no_stubs():
    for name in NODE_NAMES:
        fn = DEFAULT_NODES[name]
        assert callable(fn)
        assert not fn.__name__.endswith("_stub"), f"{name} 仍是 stub"


def test_nodes_cover_all_twelve():
    assert len(NODE_NAMES) == 12
    assert set(NODE_NAMES) == set(DEFAULT_NODES.keys())
```

- [ ] **Step 2: 运行测试（若仍有 stub 会失败，补齐登记后通过）**

Run: `poetry run pytest tests/test_integration.py -v`
Expected: 2 passed

- [ ] **Step 3: 全量测试**

Run: `poetry run pytest -v`
Expected: 全部 passed（预计 30+ 用例）

- [ ] **Step 4: 重写 README.md**

````markdown
# biaoshu_gen —— 软件标书智能体 POC

上传招标文件（docx）与企业知识库，自动解析招标要求并生成投标文件草稿。
设计文档：`docs/superpowers/specs/2026-08-18-biaoshu-agent-poc-design.md`

## 技术栈

Python 3.11+ · poetry · LangGraph（单一状态图 + SqliteSaver 断点续跑）·
PydanticAI + DeepSeek（结构化输出节点）· Claude Code SDK（harness 文件操作节点，
继承本机 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN 智谱网关环境）

## 安装

```bash
poetry install
cp .env.example .env   # 或手动在 .env 写入 DEEPSEEK_API_KEY=sk-xxx
```

## 数据准备

```bash
# 招标文件放入 data/tender/（可同时放响应文件模板 *模板*.docx，init 会自动发现）
cp docs/软件招标文件.docx docs/标书模板.docx data/tender/
# 企业知识库放入 data/company/（docx/md/txt/jpg 等）
cp docs/营业执照测试.jpg data/company/
```

## 分阶段使用（人工控制点：03_facts.yaml / 04_outline.yaml 可编辑后续跑）

```bash
poetry run biaoshu init --tender data/tender/软件招标文件.docx --kb data/company
poetry run biaoshu parse      # 招标解析（按目录分节阅读）→ 01_parse/
poetry run biaoshu template   # 响应模板抽取（harness）→ 02_template/
poetry run biaoshu facts      # 全局事实 → 03_facts.yaml（可人工编辑）
poetry run biaoshu outline    # 技术方案目录 → 04_outline.yaml（可人工编辑）
poetry run biaoshu body       # 正文生成+审核检验（≤2 轮回环）→ 05_body/
poetry run biaoshu fill       # 三表并行填写（harness）→ 06_fill/
poetry run biaoshu assemble   # 拼装草稿 → 07_draft/标书草稿_v1.docx
poetry run biaoshu review     # 全面审核（harness）→ 08_review/
poetry run biaoshu revise     # 按意见修改并跑完循环（≤2 轮）
poetry run biaoshu status     # 查看进度
```

全自动（冒烟）：`poetry run biaoshu run`

## 测试

```bash
poetry run pytest        # 无 LLM 成本（假模型 + mock harness）
```
````

同时创建 `.env.example`：

```
DEEPSEEK_API_KEY=sk-你的DeepSeek密钥
```

- [ ] **Step 5: 手动端到端冒烟（真实调用，人工执行）**

按验收标准逐条核验（设计文档 §9）：

```bash
poetry run biaoshu init --tender data/tender/软件招标文件.docx --kb data/company
poetry run biaoshu run
poetry run biaoshu status
```

核验：`07_draft/标书草稿_v1.docx` 存在且包含模板结构+技术方案正文+表格+偏离表+商务响应；`08_review/review_round_1.md` 生成且包含废标项检查结果与 VERDICT 行；回环轮次不超上限。冒烟中发现的 prompt/工程问题就地修复并补充对应测试。

- [ ] **Step 6: Commit**

```bash
git add README.md .env.example tests/test_integration.py
git commit -m "docs: README 与端到端集成校验"
```

---

## 计划自检记录（writing-plans Self-Review）

1. **Spec 覆盖**：spec §3 的 12 节点 ↔ Task 8/11/12/13/14/15/16；§4 目录布局 ↔ 各节点落盘路径；§5 CLI ↔ Task 10；§6 工程结构 ↔ 各任务 Files；§7 错误处理 ↔ Task 7（重试/产物校验）、Task 9（回环上限）、Task 13（字数容差）、Task 12（用户编辑校验）、Task 10（error.log）；§8 测试策略 ↔ 各任务 TDD + conftest 假模型 + mock harness + Task 17 集成；§9 验收 ↔ Task 17 冒烟；目录分节阅读（2026-08-18 变更）↔ Task 3 `docx_to_sections` + Task 8 分类抽取。
2. **占位符**：无 TBD/TODO；所有代码步骤给出完整代码。
3. **类型一致性**：`BidState` 字段名在各节点返回 dict 中逐一核对（forms_docx_path 等 06_fill 路径已同步为子目录隔离后的形式）；`prepare_agent_workspace` 统一命名（Task 14 定义、Task 16 复用）。
4. **已知执行期风险**（非计划缺陷，执行时以安装版本为准调整）：pydantic-ai `OpenAIChatModel` 构造签名；langgraph 条件边 list 返回值是否需要显式 path_map；claude-agent-sdk `query`/`ClaudeAgentOptions` 参数名；poetry 依赖版本区间解析。



