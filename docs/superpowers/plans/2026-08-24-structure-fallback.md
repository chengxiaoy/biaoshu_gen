# 无标题样式文档结构兜底(LLM 重建) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 当 docx 转 sections 后标题样式明显过少/形同虚设时,用一次 PydanticAI 结构化调用重建章节边界,使 parse 对"不标准格式"招标文件不再静默产出空 yaml。

**Architecture:** 检测留在纯函数 `docx_io`(阈值判断 + 编号块渲染);重建编排放新模块 `nodes/structure.py`(块化 → LLM 定界 → 代码校验 → 本地切分);`nodes/parse_tender.py` 三行接线,routing.yaml 写入 `structure_mode` 留痕。下游零改动。

**Tech Stack:** python-docx、PydanticAI(Agent/FunctionModel)、pydantic BaseModel、pytest

## Global Constraints

- 测试命令一律用 `.venv/Scripts/python.exe -m pytest`(bash 无 poetry)
- `docx_io.py` 保持纯函数:**禁止**在该模块 import 任何 LLM 相关符号(models/pydantic_ai)
- LLM 只决定边界(index/level/title);切分内容永远取自原 docx 块,不得使用模型返回的正文
- 结构化输出经 `schemas.py` 定义;校验失败重试一次封顶,再失败响亮抛 `StructureError`
- 提交信息中文、`类型:` 前缀(对齐仓库历史);每个任务收尾必须全量测试绿后提交

---

### Task 1: 触发检测 `needs_structure_fallback`

**Files:**
- Modify: `src/biaoshu_gen/docx_io.py`(文件末尾追加)
- Test: `tests/test_docx_io.py`

**Interfaces:**
- Produces: `needs_structure_fallback(sections: list[DocxSection]) -> bool`;常量 `_UNSTRUCTURED_MIN_CHARS = 2000`、`_UNSTRUCTURED_MAX_AVG = 8000`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_docx_io.py`:

```python
def _big_unstructured_docx(path: Path) -> None:
    """零 Heading 样式的大文档(模拟'不标准格式'招标文件)。"""
    doc = Document()
    doc.add_paragraph("第一章 采购需求")            # 普通段落,非 Heading 样式
    doc.add_paragraph("本系统需支持不少于 1000 并发。" * 80)   # ~1600 字
    doc.add_paragraph("第二章 评标办法")
    doc.add_paragraph("价格分采用低价优先法计算。" * 80)
    doc.save(path)


def test_needs_structure_fallback_triggers_on_no_heading(tmp_path: Path):
    p = tmp_path / "bad.docx"
    _big_unstructured_docx(p)
    assert needs_structure_fallback(docx_to_sections(p)) is True


def test_needs_structure_fallback_skips_small_docs(tmp_path: Path):
    """体量不足 _UNSTRUCTURED_MIN_CHARS 的文档不触发(避免小样张浪费 LLM 调用)。"""
    p = tmp_path / "small.docx"
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("项目名称:测试项目")
    doc.save(p)
    assert needs_structure_fallback(docx_to_sections(p)) is False


def test_needs_structure_fallback_triggers_on_huge_avg_section():
    """有标题但平均节长超限('不正确')也触发。"""
    from biaoshu_gen.docx_io import DocxSection as DS
    direct = [DS(1, "第一章 综合说明", "填充内容。" * 1500),   # 单节 ~9000 字
              DS(1, "第二章 附则", "略")]
    assert needs_structure_fallback(direct) is True


def test_needs_structure_fallback_false_for_healthy_docs():
    healthy = [DocxSection(1, f"第{i}章 说明", "内容。" * 200) for i in range(1, 7)]
    assert needs_structure_fallback(healthy) is False
```

并在该测试文件顶部 import 行加入 `needs_structure_fallback`(`from biaoshu_gen.docx_io import (...)`)。

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_docx_io.py -k fallback -v`
Expected: FAIL `ImportError: cannot import name 'needs_structure_fallback'`

- [ ] **Step 3: Write minimal implementation**

追加到 `src/biaoshu_gen/docx_io.py` 末尾:

```python
# —— 无标题样式文档的结构兜底(检测端;重建见 nodes/structure.py)——
_UNSTRUCTURED_MIN_CHARS = 2000   # 体量低于此值不判"结构缺失",避免小样张浪费 LLM 调用
_UNSTRUCTURED_MAX_AVG = 8000     # 有标题但平均节长超此值 => 标题形同虚设


def needs_structure_fallback(sections: list[DocxSection]) -> bool:
    """标题节数过少('明显过少')或平均节长过大('不正确')时需要 LLM 重建结构。"""
    total = sum(len(s.content) for s in sections)
    if total < _UNSTRUCTURED_MIN_CHARS:
        return False
    titled = sum(1 for s in sections if s.level)
    avg = total / max(len(sections), 1)
    return titled < 3 or avg > _UNSTRUCTURED_MAX_AVG
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_docx_io.py -v`
Expected: 全部 PASS(含原有测试)

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/docx_io.py tests/test_docx_io.py
git commit -m "feat: docx_io 新增无标题样式文档的结构兜底检测 needs_structure_fallback"
```

---

### Task 2: 编号块渲染 `iter_numbered_blocks`

**Files:**
- Modify: `src/biaoshu_gen/docx_io.py`(追加)
- Test: `tests/test_docx_io.py`

**Interfaces:**
- Consumes: 现有 `iter_block_items`、`_table_md`、`Paragraph`、`Table`
- Produces: `NumberedBlock`(dataclass:`index:int, kind:str("p"|"table"), stub:str, md:str`)与 `iter_numbered_blocks(doc: DocumentType) -> list[NumberedBlock]`。`stub`=prompt 用的一行摘要(表格压成 `[n] 前缀` 由渲染方拼,这里存内容摘要 ≤60 字);`md`=切分用的完整 Markdown(段落原文/整表管道表格)

- [ ] **Step 1: Write the failing test**

```python
def test_iter_numbered_blocks_numbers_and_stubs_tables():
    from biaoshu_gen.docx_io import iter_numbered_blocks

    doc = Document()
    doc.add_paragraph("")                                # 空段跳过
    doc.add_paragraph("第一章 采购需求")
    t = doc.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "名称"
    t.cell(0, 1).text = "数量"
    t.cell(1, 0).text = "应用软件 A"
    t.cell(1, 1).text = "1 套"
    doc.add_paragraph("以上设备须为全新原装。")

    blocks = iter_numbered_blocks(doc)
    assert [(b.index, b.kind) for b in blocks] == [(0, "p"), (1, "table"), (2, "p")]
    assert blocks[0].stub == "第一章 采购需求"
    assert "【表格】" in blocks[1].stub and "名称" in blocks[1].stub
    assert "| 名称 | 数量 |" in blocks[1].md and "| 应用软件 A | 1 套 |" in blocks[1].md
    assert blocks[2].md == "以上设备须为全新原装。"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_docx_io.py -k numbered -v`
Expected: FAIL `ImportError: cannot import name 'iter_numbered_blocks'`

- [ ] **Step 3: Write minimal implementation**

追加到 `src/biaoshu_gen/docx_io.py`:

```python
@dataclass
class NumberedBlock:
    """非空内容块的编号视图:prompt 摘要(stub)与切分全文(md)一体两用。"""
    index: int          # 非空块序号,与 LLM prompt 编号一致
    kind: str           # 'p'=段落 | 'table'=表格
    stub: str           # prompt 用一行摘要;表格压成【表格】+首行内容(≤60 字)
    md: str             # 切分用完整内容;段落原文 / 整表管道表格


def iter_numbered_blocks(doc: DocumentType) -> list[NumberedBlock]:
    """按文档顺序产出非空块的编号视图(空段跳过,编号连续)。"""
    blocks: list[NumberedBlock] = []
    for item in iter_block_items(doc):
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            blocks.append(NumberedBlock(len(blocks), "p", text, text))
        else:
            rows = item.rows
            first = "/".join(c.text.strip() for c in rows[0].cells) if rows else ""
            stub = ("【表格】" + first)[:66]
            blocks.append(NumberedBlock(len(blocks), "table", stub, _table_md(item)))
    return blocks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_docx_io.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/docx_io.py tests/test_docx_io.py
git commit -m "feat: docx_io 新增编号块视图 iter_numbered_blocks(段落/表格 stub+全文)"
```

---

### Task 3: 输出模型 + 校验/切分纯函数(nodes/structure.py 前半)

**Files:**
- Modify: `src/biaoshu_gen/schemas.py`(末尾追加两个模型)
- Create: `src/biaoshu_gen/nodes/structure.py`
- Test: `tests/test_node_structure.py`(新建)

**Interfaces:**
- Produces:
  - `schemas.StructureHeading(BaseModel)`: `index:int, level:int, title:str`
  - `schemas.StructureOutline(BaseModel)`: `headings:list[StructureHeading]`(默认空列表)
  - `structure.StructureError(RuntimeError)`
  - `structure.validate_headings(outline: StructureOutline, n_blocks: int) -> list[StructureHeading]`(乱序/越界 index 丢弃、空或 >50 字 title 丢弃、level 夹取 1~3、首个强制 1)
  - `structure.split_by_headings(blocks: list[NumberedBlock], headings: list[StructureHeading]) -> list[DocxSection]`(首标题前为 `(前言)` level 0,内容为空的前言节丢弃)

- [ ] **Step 1: Write the failing test**

新建 `tests/test_node_structure.py`:

```python
from biaoshu_gen.docx_io import DocxSection, NumberedBlock
from biaoshu_gen.nodes import structure as st
from biaoshu_gen.schemas import StructureHeading, StructureOutline


def _block(i: int, text: str) -> NumberedBlock:
    return NumberedBlock(index=i, kind="p", stub=text, md=text)


def test_validate_headings_drops_bad_and_clamps():
    outline = StructureOutline.model_validate({"headings": [
        {"index": 3, "level": 1, "title": "第三章 评标办法"},
        {"index": 1, "level": 1, "title": "第一章 总体要求"},      # 乱序 -> 丢弃
        {"index": 5, "level": 9, "title": "第五章 附则"},          # level 夹取 3
        {"index": 7, "level": 2, "title": ""},                     # 空 title 丢弃
        {"index": 8, "level": 2, "title": "x" * 51},               # 超 50 字丢弃
        {"index": 9, "level": 0, "title": "第六章 其他"},          # level 夹取 1
    ]})
    hs = st.validate_headings(outline, n_blocks=12)
    assert [(h.index, h.level, h.title) for h in hs] == [
        (3, 1, "第三章 评标办法"), (5, 3, "第五章 附则"), (9, 1, "第六章 其他")]
    assert hs[0].index == 3                                        # 幸存者首位强制 level 1 已是 1


def test_split_by_headings_assigns_content_and_preamble():
    blocks = [_block(i, t) for i, t in enumerate([
        "封面文字", "第一章 总体要求", "系统需支持 1000 并发。",
        "1.1 性能指标", "响应时间 ≤ 2 秒。", "第二章 商务条款", "质保三年。",
    ])]
    headings = [StructureHeading(index=1, level=1, title="第一章 总体要求"),
                StructureHeading(index=3, level=3, title="1.1 性能指标"),
                StructureHeading(index=5, level=1, title="第二章 商务条款")]
    secs = st.split_by_headings(blocks, headings)
    assert [(s.level, s.title) for s in secs] == [
        (0, "(前言)"), (1, "第一章 总体要求"), (3, "1.1 性能指标"), (1, "第二章 商务条款")]
    assert secs[0].content == "封面文字"
    assert "1000 并发" in secs[1].content
    assert "响应时间" in secs[2].content
    assert "质保三年" in secs[3].content


def test_split_by_headings_drops_empty_preamble():
    blocks = [_block(i, t) for i, t in enumerate(["第一章 总则", "正文若干。"])]
    secs = st.split_by_headings(blocks, [StructureHeading(index=0, level=1, title="第一章 总则")])
    assert [(s.level, s.title) for s in secs] == [(1, "第一章 总则")]
```

`schemas.py` 末尾追加(先跑测试看 ImportError 再加):

```python
class StructureHeading(BaseModel):
    """无标题样式文档重建出的单个章节边界(块序号定界)。"""
    index: int
    level: int
    title: str


class StructureOutline(BaseModel):
    """LLM 结构重建输出:按文档块序排列的章节标题列表。"""
    headings: list[StructureHeading] = Field(default_factory=list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_node_structure.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'biaoshu_gen.nodes.structure'`

- [ ] **Step 3: Write minimal implementation**

新建 `src/biaoshu_gen/nodes/structure.py`:

```python
"""无标题样式文档的结构重建:LLM 定界 + 代码校验 + 本地切分(设计见 specs/2026-08-24)。"""
from biaoshu_gen.docx_io import DocxSection, NumberedBlock
from biaoshu_gen.schemas import StructureHeading, StructureOutline

_MAX_TITLE = 50


class StructureError(RuntimeError):
    """结构重建失败(LLM 两次输出均未通过校验)。"""


def validate_headings(outline: StructureOutline, n_blocks: int) -> list[StructureHeading]:
    """代码侧硬校验:乱序/越界 index 与非法 title 丢弃,level 夹取 1~3,幸存首位强制 1 级。"""
    out: list[StructureHeading] = []
    last = -1
    for h in outline.headings:
        if not (0 <= h.index < n_blocks) or h.index <= last:
            continue
        title = h.title.strip()
        if not title or len(title) > _MAX_TITLE:
            continue
        level = min(max(h.level, 1), 3)
        if not out:
            level = 1
        out.append(StructureHeading(index=h.index, level=level, title=title))
        last = h.index
    return out


def split_by_headings(blocks: list[NumberedBlock],
                      headings: list[StructureHeading]) -> list[DocxSection]:
    """按标题边界本地切分:内容取自原块 md,LLM 只决定归属。"""
    bounds = {h.index: h for h in headings}
    secs: list[DocxSection] = []
    cur = DocxSection(0, "(前言)", "")

    def flush():
        nonlocal cur
        if cur.content or cur.level:
            secs.append(cur)

    for b in blocks:
        h = bounds.get(b.index)
        if h is not None:
            flush()
            cur = DocxSection(h.level, h.title, "")
        cur.content = (cur.content + "\n\n" + b.md).strip()
    flush()
    return secs
```

`schemas.py` 追加上述两个模型(import 区已有 `Field` 则不必重复导入,先确认文件头)。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_node_structure.py tests/test_schemas.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/schemas.py src/biaoshu_gen/nodes/structure.py tests/test_node_structure.py
git commit -m "feat: 结构重建输出模型与校验/切分纯函数(validate_headings, split_by_headings)"
```

---

### Task 4: Prompt + `rebuild_sections` 编排(单次调用,校验失败重试一次)

**Files:**
- Create: `src/biaoshu_gen/prompts/structure.py`
- Modify: `src/biaoshu_gen/nodes/structure.py`(追加编排)
- Test: `tests/test_node_structure.py`(追加)

**Interfaces:**
- Consumes: `docx_io.iter_numbered_blocks`、`make_agent/run_sync`(`..models`,节点内惯例 import,测试 monkeypatch `st.make_agent`)、Task 3 的校验/切分
- Produces: `prompts.structure.SYSTEM`、`prompts.structure.build_user_prompt(blocks_text: str) -> str`;`structure.rebuild_sections(path: Path) -> list[DocxSection]`(两次校验失败抛 `StructureError`)

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_node_structure.py`:

```python
import json

import pytest
from docx import Document
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from biaoshu_gen.schemas import StructureOutline


def _unstructured_tender(tmp_path):
    p = tmp_path / "ns.docx"
    doc = Document()
    doc.add_paragraph("第一章 采购需求")
    doc.add_paragraph("内容甲。" * 30)
    doc.add_paragraph("第二章 评标办法")
    doc.add_paragraph("内容乙。" * 30)
    doc.save(p)
    return p


def _fake_make(responses: list[str]):
    """按调用次序返回预设 JSON 的假 agent 工厂;记录收到的 prompt。"""
    calls: list[str] = []

    def make(output_type, system_prompt, retries=2):
        def fn(messages, info: AgentInfo):
            calls.append(messages[-1].parts[-1].content)
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            payload = responses[min(len(calls) - 1, len(responses) - 1)]
            return ModelResponse(parts=[ToolCallPart(tool=tool, args=payload)])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    make.calls = calls
    return make


def test_rebuild_sections_happy_path(tmp_path, monkeypatch):
    p = _unstructured_tender(tmp_path)
    make = _fake_make([json.dumps({"headings": [
        {"index": 0, "level": 1, "title": "第一章 采购需求"},
        {"index": 2, "level": 1, "title": "第二章 评标办法"},
    ]}, ensure_ascii=False)])
    monkeypatch.setattr(st, "make_agent", make)
    secs = st.rebuild_sections(p)
    assert [(s.level, s.title) for s in secs] == [
        (1, "第一章 采购需求"), (1, "第二章 评标办法")]
    assert "内容甲" in secs[0].content
    prompt = make.calls[0]
    assert "[0] 第一章 采购需求" in prompt and "【表格】" not in prompt
    assert "目录" in prompt                                    # 去目录指引在 prompt 中


def test_rebuild_sections_retries_once_with_error_feedback(tmp_path, monkeypatch):
    p = _unstructured_tender(tmp_path)
    bad = json.dumps({"headings": [{"index": 2, "level": 1, "title": "第二章"}]})
    good = json.dumps({"headings": [
        {"index": 0, "level": 1, "title": "第一章 采购需求"},
        {"index": 2, "level": 1, "title": "第二章 评标办法"}]}, ensure_ascii=False)
    make = _fake_make([bad, good])
    monkeypatch.setattr(st, "make_agent", make)
    secs = st.rebuild_sections(p)
    assert len(make.calls) == 2
    assert "错误" in make.calls[1]                             # 第二次 prompt 带错误反馈
    assert len(secs) == 2


def test_rebuild_sections_raises_after_retry_exhausted(tmp_path, monkeypatch):
    p = _unstructured_tender(tmp_path)
    bad = json.dumps({"headings": [{"index": 5, "level": 1, "title": "越界"}]})
    make = _fake_make([bad])
    monkeypatch.setattr(st, "make_agent", make)
    with pytest.raises(st.StructureError):
        st.rebuild_sections(p)
    assert len(make.calls) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_node_structure.py -k rebuild -v`
Expected: FAIL `ImportError: cannot import name 'SYSTEM'`(prompts/structure.py 不存在)

- [ ] **Step 3: Write minimal implementation**

新建 `src/biaoshu_gen/prompts/structure.py`:

```python
"""无标题样式文档的结构重建 prompt(单次结构化调用)。"""

SYSTEM = "你是标书文档结构分析师,从缺少标题样式的招标类文档编号块中识别章节标题与层级。"

TEMPLATE = """下面是按文档顺序编号的内容块([序号] 内容;表格压成一行摘要)。
任务:找出全部章节标题所在块,构成文档结构。

判定规则:
- 层级最多 3 级:第X章/第一部分 → 1 级;一、/1. 序号小节 → 2 级;(一)/1.1 条款 → 3 级
- 目录页、封面、声明类的条目不算章节标题;同一标题正文重复出现时取正文那次
- 标题必须是独立的短块(一般不超过 50 字);含序号的长句是条款正文,不是标题
- 找不到任何标题时返回空列表

输出 headings: [{index, level, title}],index 为块序号。

内容块:
{blocks}"""


def build_user_prompt(blocks_text: str) -> str:
    return TEMPLATE.format(blocks=blocks_text)
```

`src/biaoshu_gen/nodes/structure.py` 追加:

```python
from pathlib import Path

from docx import Document

from ..docx_io import iter_numbered_blocks
from ..models import make_agent, run_sync       # noqa: F401  (测试 monkeypatch st.make_agent)
from ..prompts.structure import SYSTEM, build_user_prompt
from ..schemas import StructureOutline

_RETRY_TIMES = 2   # 首次 + 校验失败重试一次


def rebuild_sections(path: Path) -> list[DocxSection]:
    """无标题样式文档的结构重建:块化 -> 单次 LLM 定界 -> 硬校验(失败带错重试一次)-> 本地切分。"""
    blocks = iter_numbered_blocks(Document(str(path)))
    blocks_text = "\n".join(f"[{b.index}] {b.stub}" for b in blocks)
    agent = make_agent(StructureOutline, SYSTEM)

    prompt = build_user_prompt(blocks_text)
    headings: list[StructureHeading] = []
    err = "未得到任何有效标题"
    for _ in range(_RETRY_TIMES):
        outline: StructureOutline = run_sync(agent, prompt).output
        headings = validate_headings(outline, n_blocks=len(blocks))
        if headings:
            break
        prompt = build_user_prompt(blocks_text) + f"\n\n上一次输出未通过校验(错误:{err}),请修正后重新输出。"
    if not headings:
        raise StructureError(f"结构重建失败:文档 {path} 两次输出均无有效标题(最后错误:{err})")
    return split_by_headings(blocks, headings)
```

说明:`err` 变量当前恒为初值(校验函数暂不返回错误明细),保持接口简单;重试反馈已足以引导模型。若后续需要明细,再让 `validate_headings` 返回 `(list, str)`,本任务不做。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_node_structure.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/prompts/structure.py src/biaoshu_gen/nodes/structure.py tests/test_node_structure.py
git commit -m "feat: rebuild_sections 编排(块化->LLM 定界->校验重试一次->本地切分)"
```

---

### Task 5: parse 节点接线 + routing.yaml 留痕

**Files:**
- Modify: `src/biaoshu_gen/nodes/parse_tender.py`
- Modify: `README.md`(解析阶段验收点一句话)
- Test: `tests/test_node_parse_tender.py`(追加)

**Interfaces:**
- Consumes: `docx_io.needs_structure_fallback`、`nodes.structure.rebuild_sections`
- Produces: `parse_tender_node` 在兜底触发时以重建 sections 继续;`routing.yaml` 首键 `structure_mode: heading|llm_rebuild`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_node_parse_tender.py`:

```python
def _state_unstructured(tmp_path: Path, monkeypatch) -> BidState:
    monkeypatch.chdir(tmp_path)
    tender = tmp_path / "ns.docx"
    d = Document()
    d.add_paragraph("第一章 采购需求")
    d.add_paragraph("系统需支持 1000 并发,提供三年质保。" * 100)   # >2000 字触发兜底
    d.add_paragraph("第二章 评标办法")
    d.add_paragraph("价格分采用低价优先法计算。" * 100)
    d.save(tender)
    return BidState(run_id="run-ns", tender_path=str(tender))


def test_parse_tender_falls_back_to_llm_rebuild(tmp_path: Path, monkeypatch):
    import yaml as _yaml
    state = _state_unstructured(tmp_path, monkeypatch)

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            if output_type is StructureOutline:
                out = {"headings": [
                    {"index": 0, "level": 1, "title": "第一章 采购需求"},
                    {"index": 2, "level": 1, "title": "第二章 评标办法"}]}
            elif output_type is TenderRequirements:
                out = {"tech_requirements": ["1000 并发"]}
            else:
                out = {}
            return ModelResponse(parts=[ToolCallPart(tool=tool, args=json.dumps(out))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(pt, "make_agent", make)
    monkeypatch.setattr(pt_structure, "make_agent", make)   # 兜底编排同样注入假模型
    updates = pt.parse_tender_node(state)

    d = run_dir(state) / "01_parse"
    routing = _yaml.safe_load((d / "routing.yaml").read_text(encoding="utf-8"))
    assert routing["structure_mode"] == "llm_rebuild"
    md = (d / "tender.md").read_text(encoding="utf-8")
    assert "# 第一章 采购需求" in md                        # 重建后的层级进入 tender.md
    assert updates["requirements"].tech_requirements == ["1000 并发"]


def test_parse_tender_keeps_heading_mode_when_structured(tmp_path: Path, monkeypatch):
    import yaml as _yaml
    state = _state(tmp_path, monkeypatch)                   # 3 个 Heading 的小文档
    called = {"structure": 0}

    def make(output_type, system_prompt, retries=2):
        if output_type is StructureOutline:
            called["structure"] += 1
        async def fn(messages, info: AgentInfo):
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            return ModelResponse(parts=[ToolCallPart(tool=tool, args=json.dumps({}))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(pt, "make_agent", make)
    monkeypatch.setattr(pt_structure, "make_agent", make)
    pt.parse_tender_node(state)
    routing = _yaml.safe_load(
        (run_dir(state) / "01_parse" / "routing.yaml").read_text(encoding="utf-8"))
    assert routing["structure_mode"] == "heading"
    assert called["structure"] == 0                         # 正常文档不发生结构重建调用
```

并在文件头部补 import:

```python
from biaoshu_gen.nodes import structure as pt_structure
from biaoshu_gen.schemas import StructureOutline
```

(`json/yaml` 文件里已 import `json`;`import yaml as _yaml` 放测试函数内即可。)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_node_parse_tender.py -k "falls_back or keeps_heading" -v`
Expected: FAIL(KeyError `'structure_mode'` 或断言不等)

- [ ] **Step 3: Write minimal implementation**

`src/biaoshu_gen/nodes/parse_tender.py` 三处改动:

```python
# import 区新增
from ..docx_io import DocxSection, docx_to_sections, needs_structure_fallback, sections_to_markdown
from .structure import rebuild_sections
```

`parse_tender_node` 开头替换为:

```python
def parse_tender_node(state: BidState) -> dict:
    sections = docx_to_sections(Path(state.tender_path))

    # ⓪ 结构兜底:标题样式过少/形同虚设时,LLM 重建章节边界(routing.yaml 留痕)
    mode = "heading"
    if needs_structure_fallback(sections):
        sections = rebuild_sections(Path(state.tender_path))
        mode = "llm_rebuild"

    # ① 目录路由:...(以下不变)
```

落盘处 routing 字典前插一个键:

```python
    routing = {"structure_mode": mode,
               **{g: [f"{i}. {sections[i - 1].title}" for i in idx] for g, idx in by_group.items()}}
```

`README.md` 解析行验收点改为:

```markdown
| 解析 | `biaoshu parse` | `01_parse/`:metadata/requirements/scoring/invalidation 四 yaml 非空、`routing.yaml` 为关键词路由结果(含 `structure_mode`,无标题样式文档自动 LLM 重建结构)、`tender.md` 全文 |
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全量 PASS(确认既有 parse/body/graph 测试无回归)

- [ ] **Step 5: Commit**

```bash
git add src/biaoshu_gen/nodes/parse_tender.py tests/test_node_parse_tender.py README.md
git commit -m "feat: parse 节点接入结构兜底,routing.yaml 记录 structure_mode"
```

---

### Task 6: 真实样本验收(手动,真实 LLM)

**Files:**
- 只读消费:`data/tender/不标准格式招标文件.docx`
- 产物:`data/runs/<新 run_id>/01_parse/*`

**Interfaces:**
- Consumes: Task 1-5 全部产物;真实 llm 三件套(.env)

- [ ] **Step 1: 新开 run 并解析真实不标准样本**

```bash
export PYTHONIOENCODING=utf-8
cd C:/Users/cheng/PycharmProjects/biaoshu_gen
.venv/Scripts/biaoshu init --tender "data/tender/不标准格式招标文件.docx" --kb data/company
.venv/Scripts/biaoshu parse
```

- [ ] **Step 2: 验收检查**

```bash
cat data/runs/$(ls -t data/runs | head -1)/01_parse/routing.yaml | head -20
```

Expected:
- `structure_mode: llm_rebuild`;
- 四组(metadata/requirements/scoring/invalidation)至少一组命中多个章节(scoring 应命中「评审因素和标准」相关节);
- `metadata.yaml`/`requirements.yaml`/`scoring.yaml`/`invalidation.yaml` 均存在且关键内容非空(scoring.yaml 含评分规则条目);
- `tender.md` 开头可见 `# 第…章` 层级标题。

任一不满足 → 回到对应任务修缺陷后重跑本步。

- [ ] **Step 3: 收尾提交(如有微调)**

若验收过程产生代码修正,单独提交:

```bash
git add -A && git commit -m "fix: 结构兜底真实样本验收修正"
```
