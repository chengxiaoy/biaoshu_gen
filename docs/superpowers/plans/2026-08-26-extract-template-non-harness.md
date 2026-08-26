# extract_template 非 harness 化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 extract_template 节点从 harness 子进程代理改为「LLM 定界 + python 剪裁 + 确定性派生 md」,消灭逐段探查开销。

**Architecture:** 复用结构兜底的「LLM 只定界」模式——iter_numbered_blocks 块化后单次 PydantaiAI 调用返回格式章节的起止块序号,代码硬校验(重试一次封顶),再映射到 body 元素下标做整包副本删区间剪裁;template.md/report.md 由剪裁副本确定性派生,零 LLM。

**Tech Stack:** python-docx、PydanticAI(make_agent/run_sync,OpenAI 协议三件套)、pytest。

**Spec:** docs/superpowers/specs/2026-08-24-extract-template-non-harness-design.md

## Global Constraints

- 测试命令:`.venv/Scripts/python.exe -m pytest …`(bash 无 poetry);每任务结束全量回归必须全过
- `docx_io.py` 保持纯函数:禁止 import 任何 LLM 模块(models/make_agent/pydantic_ai)
- LLM 只定界:剪裁内容永远取原招标文档元素;校验失败带错重试一次封顶(`_RETRY_TIMES = 2`)
- 节点返回值契约不变:`{"template_docx_path": str(<run>/02_template/标书模板.docx)}`
- 提交消息用中文前缀(feat:/fix:/refactor:/test:/docs:)
- pydantic-ai 1.107.5:FunctionModel 回调必须返回 `ModelResponse`(ToolCallPart 用 `tool_name=` 关键字)
- 既有消费方不得破坏:`nodes/structure.py` 消费 `NumberedBlock(index/kind/stub/md)` 与 `iter_numbered_blocks`;新增字段一律带默认值

---

### Task 1: docx_io —— NumberedBlock 元素定位字段 + clip_docx

**Files:**
- Modify: `src/biaoshu_gen/docx_io.py`(NumberedBlock 约 214-239 行、末尾追加 clip_docx)
- Test: `tests/test_docx_io.py`(追加两个测试)

**Interfaces:**
- Consumes: 既有 `_full_text(para)`、`_table_md(table)`、`Document`、`Paragraph`、`Table`、`qn`(均已在 docx_io 顶部导入)
- Produces(供后续任务使用,签名精确):
  - `NumberedBlock` 新增字段 `element: object | None = None`、`element_index: int = -1`(既有四字段位置与关键字构造不变)
  - `iter_numbered_blocks(doc: DocumentType) -> list[NumberedBlock]`:element/element_index 填充为 body 子元素及其下标(**跳过空段但下标按 body 子元素连续计数**)
  - `clip_docx(src: Path, dest: Path, start_index: int, end_index: int) -> None`:整包 copyfile 后删除 `[start,end)` 之外的全部 body 子元素并保存;`end_index` 独占;`w:sectPr` 固定保留

- [ ] **Step 1: 写失败测试**(tests/test_docx_io.py 追加;文件顶部已 import Document/Path)

```python
def test_iter_numbered_blocks_records_element_index():
    from biaoshu_gen.docx_io import iter_numbered_blocks

    doc = Document()
    doc.add_paragraph("")                        # 空段:跳过不编号,但 body 下标仍占位
    doc.add_paragraph("第一章 采购需求")
    t = doc.add_table(rows=1, cols=1)
    t.cell(0, 0).text = "报价表"

    blocks = iter_numbered_blocks(doc)
    children = list(doc.element.body.iterchildren())
    assert [(b.index, b.kind) for b in blocks] == [(0, "p"), (1, "table")]
    assert blocks[0].element_index == 1          # 空段占位 0,计数不回退
    assert blocks[0].element is children[1]
    assert blocks[1].element_index == 2 and blocks[1].element is children[2]


def test_clip_docx_keeps_range_and_sectpr(tmp_path: Path):
    from biaoshu_gen.docx_io import clip_docx, iter_numbered_blocks

    src = tmp_path / "t.docx"
    doc = Document()
    doc.add_paragraph("第二章 投标人须知")
    doc.add_paragraph("须知正文。")
    doc.add_paragraph("第七章 投标文件的格式")
    doc.add_paragraph("投标函格式正文。")
    doc.save(src)

    probe = Document(str(src))
    blocks = iter_numbered_blocks(probe)
    start = next(b.element_index for b in blocks if b.stub.startswith("第七章"))
    end = len(list(probe.element.body.iterchildren()))

    dest = tmp_path / "tpl.docx"
    clip_docx(src, dest, start, end)
    out = Document(str(dest))
    texts = [p.text for p in out.paragraphs]
    assert any("投标文件的格式" in x for x in texts)
    assert any("投标函" in x for x in texts)
    assert not any("投标人须知" in x for x in texts)
    assert out.element.body.sectPr is not None


def test_clip_docx_excludes_end_boundary(tmp_path: Path):
    """end_index 指向的元素本身不属于模板(独占)。"""
    from biaoshu_gen.docx_io import clip_docx, iter_numbered_blocks

    src = tmp_path / "t.docx"
    doc = Document()
    doc.add_paragraph("第七章 投标文件的格式")
    doc.add_paragraph("投标函格式正文。")
    doc.add_paragraph("第八章 其他事项")
    doc.save(src)

    probe = Document(str(src))
    blocks = iter_numbered_blocks(probe)
    start = next(b.element_index for b in blocks if b.stub.startswith("第七章"))
    end = next(b.element_index for b in blocks if b.stub.startswith("第八章"))

    dest = tmp_path / "tpl.docx"
    clip_docx(src, dest, start, end)
    texts = [p.text for p in Document(str(dest)).paragraphs]
    assert any("投标函" in x for x in texts)
    assert not any("第八章" in x for x in texts)
```

- [ ] **Step 2: 跑红**

Run: `.venv/Scripts/python.exe -m pytest tests/test_docx_io.py -v -k "element_index or clip_docx"`
Expected: FAIL —— `NumberedBlock` 无 `element_index` 属性(AttributeError)/ `cannot import name 'clip_docx'`

- [ ] **Step 3: 最小实现**

docx_io.py 的 `NumberedBlock` 改为(保留原注释风格):

```python
@dataclass
class NumberedBlock:
    """非空内容块的编号视图:prompt 摘要(stub)与切分全文(md)一体两用。"""
    index: int          # 非空块序号,与 LLM prompt 编号一致
    kind: str           # 'p'=段落 | 'table'=表格
    stub: str           # prompt 用一行摘要;表格压成【表格】+首行内容(≤60 字)
    md: str             # 切分用完整内容;段落原文 / 整表管道表格
    element: object | None = None   # body 子元素引用(extract_template 剪裁映射用)
    element_index: int = -1         # 该元素在 body 子元素中的下标(空段也计数)
```

`iter_numbered_blocks` 改为沿 body 子元素遍历(不再经 iter_block_items):

```python
def iter_numbered_blocks(doc: DocumentType) -> list[NumberedBlock]:
    """按文档顺序产出非空块的编号视图(空段跳过不编号,element_index 按 body 连续计数)。"""
    blocks: list[NumberedBlock] = []
    for el_idx, child in enumerate(doc.element.body.iterchildren()):
        if child.tag == qn("w:p"):
            text = _full_text(Paragraph(child, doc)).strip()
            if not text:
                continue
            blocks.append(NumberedBlock(len(blocks), "p", text, text, child, el_idx))
        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            rows = table.rows
            first = "/".join(
                "\n".join(_full_text(p) for p in c.paragraphs).strip()
                for c in rows[0].cells) if rows else ""
            stub = ("【表格】" + first)[:66]
            blocks.append(NumberedBlock(len(blocks), "table", stub, _table_md(table), child, el_idx))
    return blocks
```

文件末尾追加:

```python
def clip_docx(src: Path, dest: Path, start_index: int, end_index: int) -> None:
    """整包副本删区间:保 [start,end) 与 sectPr,删其余 body 子元素。

    相比"新建文档拷元素",样式/编号定义/页眉页脚随包保留(fill 阶段同哲学);
    end_index 独占;sectPr 固定在 body 尾部,永不删除。
    """
    shutil.copyfile(src, dest)
    doc = Document(str(dest))
    children = list(doc.element.body.iterchildren())
    for i, el in enumerate(children):
        if start_index <= i < end_index or el.tag == qn("w:sectPr"):
            continue
        el.getparent().remove(el)
    doc.save(str(dest))
```

- [ ] **Step 4: 跑绿 + 全量回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_docx_io.py -v` 然后 `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 新 3 个测试 PASS;全量 PASS(structure 相关测试不受影响——新字段带默认值)

- [ ] **Step 5: 提交**

```bash
git add src/biaoshu_gen/docx_io.py tests/test_docx_io.py
git commit -m "feat: NumberedBlock 记录 body 元素下标,clip_docx 整包副本删区间"
```

---

### Task 2: schemas.TemplateAnchor + prompts/extract_template 重写

**Files:**
- Modify: `src/biaoshu_gen/schemas.py`(StructureOutline 之后插入)
- Rewrite: `src/biaoshu_gen/prompts/extract_template.py`(整文件替换,harness 版 prompt 作废)
- Test: `tests/test_schemas.py`(追加)

**Interfaces:**
- Consumes: 既有 BaseModel/Field 导入(schemas.py 顶部已有)
- Produces:
  - `TemplateAnchor(BaseModel)`:`start_index: int`、`end_index: int | None = None`(None=格式章节到文末)
  - `prompts.extract_template.SYSTEM: str`、`build_user_prompt(blocks_text: str) -> str`

- [ ] **Step 1: 写失败测试**(tests/test_schemas.py 追加)

```python
def test_template_anchor_end_defaults_to_none():
    from biaoshu_gen.schemas import TemplateAnchor

    assert TemplateAnchor(start_index=3).end_index is None
    a = TemplateAnchor.model_validate({"start_index": 1, "end_index": None})
    assert (a.start_index, a.end_index) == (1, None)


def test_extract_template_prompt_renders_block_lines_and_json_rule():
    from biaoshu_gen.prompts.extract_template import build_user_prompt

    p = build_user_prompt("[0] 封面\n[1] 第七章 投标文件的格式")
    assert "[1] 第七章 投标文件的格式" in p
    assert '"start_index"' in p and "null" in p     # JSON 输出指令存在且花括号转义渲染成功
```

- [ ] **Step 2: 跑红**

Run: `.venv/Scripts/python.exe -m pytest tests/test_schemas.py -v -k "template_anchor or extract_template"`
Expected: FAIL —— `cannot import name 'TemplateAnchor'` / 旧版 `build_user_prompt` 需要 bool 参数(TypeError)

- [ ] **Step 3: 实现**

schemas.py 在 `StructureOutline` 类之后插入:

```python
class TemplateAnchor(BaseModel):
    """LLM 定位的响应文件格式章节边界(块序号)。end_index=None 表示到文档末尾。"""
    start_index: int
    end_index: int | None = None
```

prompts/extract_template.py 整文件替换为:

```python
"""extract_template 节点 prompt(LLM 定界)：定位响应文件格式章节的起止块。"""

SYSTEM = "你是投标文件结构分析师，负责在招标文件中定位响应文件（投标文件）格式章节的边界。"

TEMPLATE = """以下是招标文档按顺序编号的内容块（[序号] 内容摘要；表格压缩为一行）：

{blocks_text}

任务：找出"投标文件/响应文件的格式"章节（即给出投标函、报价表、偏离表等空白格式的章节）的块边界。

判定规则：
1. start_index：格式章节标题所在块的序号（如「第七章 投标文件的格式」「第五章 响应文件组成」）
2. end_index：格式章节之后下一个章级标题（第X章）所在块的序号；格式章节直到文档末尾则为 null
3. 目录页中的条目不是章节标题；正文中引用的章节名不算
4. 只返回 JSON：{{"start_index": <整数>, "end_index": <整数或null>}}
"""


def build_user_prompt(blocks_text: str) -> str:
    return TEMPLATE.format(blocks_text=blocks_text)
```

- [ ] **Step 4: 跑绿 + 全量回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_schemas.py -v` 然后 `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS(注意:此时旧节点仍在用旧签名 build_user_prompt——若旧节点测试因 import 旧符号报错,属预期破坏,本任务只要求 schemas/prompt 自身测试绿 + 其余测试不因本任务变红;旧节点测试由 Task 3 整体重写。若全量回归中仅 tests/test_node_extract_template.py 变红,可继续 Step 5)

- [ ] **Step 5: 提交**

```bash
git add src/biaoshu_gen/schemas.py src/biaoshu_gen/prompts/extract_template.py tests/test_schemas.py
git commit -m "feat: TemplateAnchor 定界 schema 与 extract_template 定界 prompt"
```

---

### Task 3: nodes/extract_template 重写(LLM 定界 + 校验 + 剪裁 + 派生)

**Files:**
- Rewrite: `src/biaoshu_gen/nodes/extract_template.py`(harness 调用全部移除)
- Rewrite: `tests/test_node_extract_template.py`(旧 harness 测试整体废弃)

**Interfaces:**
- Consumes(Task 1/2 产物,签名精确):
  - `clip_docx(src: Path, dest: Path, start_index: int, end_index: int)`
  - `NumberedBlock.element_index: int`、`iter_numbered_blocks(doc) -> list[NumberedBlock]`
  - `TemplateAnchor(start_index, end_index=None)`、`SYSTEM`、`build_user_prompt(blocks_text)`
  - `make_agent(output_type, system_prompt, retries=2)`、`run_sync(agent, prompt)`(models.py,.output 取结构化结果)
- Produces:
  - `extract_template_node(state: BidState) -> dict`(graph 接线不变)
  - `TemplateExtractError(RuntimeError)`
  - `_validate_anchor(anchor: TemplateAnchor, n_blocks: int) -> tuple[int, int | None]`(私有,单测直接调)
  - `_extract_from_tender(tender: Path, tpl_docx: Path) -> None`(真实验收脚本复用)
  - `derive_template_md(tpl_docx: Path) -> str`、`derive_report_md(tpl_docx: Path) -> str`

- [ ] **Step 1: 写失败测试**(tests/test_node_extract_template.py 整文件替换)

```python
import json
from pathlib import Path

import pytest
from docx import Document
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from biaoshu_gen.nodes import extract_template as et
from biaoshu_gen.schemas import TemplateAnchor
from biaoshu_gen.state import BidState, run_dir


def _tender(tmp_path: Path) -> Path:
    """合成招标文件:非格式章节在前,第七章格式章节(段落+表格)在后。"""
    p = tmp_path / "tender.docx"
    doc = Document()
    doc.add_paragraph("第二章 投标人须知")
    doc.add_paragraph("递交截止时间为开标之日。")
    doc.add_paragraph("第七章 投标文件的格式")
    doc.add_paragraph("投标函（格式）")
    doc.add_paragraph("兹承诺按招标文件要求投标。")
    t = doc.add_table(rows=1, cols=1)
    t.cell(0, 0).text = "报价表"
    doc.save(p)
    return p


def _fake_make(responses: list[dict]):
    """按调用次序返回预设 JSON 的假 agent 工厂;记录收到的 prompt(structure 测试同款)。"""
    calls: list[str] = []

    def make(output_type, system_prompt, retries=2):
        def fn(messages, info: AgentInfo):
            calls.append(messages[-1].parts[-1].content)
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            payload = responses[min(len(calls) - 1, len(responses) - 1)]
            return ModelResponse(parts=[ToolCallPart(tool_name=tool, args=json.dumps(payload))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    make.calls = calls
    return make


def test_validate_anchor_normalizes_and_rejects():
    assert et._validate_anchor(TemplateAnchor(start_index=2), 6) == (2, None)
    assert et._validate_anchor(TemplateAnchor(start_index=2, end_index=6), 6) == (2, None)  # end==n 视同文末
    assert et._validate_anchor(TemplateAnchor(start_index=2, end_index=4), 6) == (2, 4)
    with pytest.raises(ValueError):
        et._validate_anchor(TemplateAnchor(start_index=6), 6)          # start 越界
    with pytest.raises(ValueError):
        et._validate_anchor(TemplateAnchor(start_index=3, end_index=3), 6)  # end 不严格大于 start


def test_node_extracts_via_llm_bounds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tender = _tender(tmp_path)
    state = BidState(run_id="run-1", tender_path=str(tender))
    make = _fake_make([{"start_index": 2, "end_index": None}])      # 块2 = 第七章标题
    monkeypatch.setattr(et, "make_agent", make)

    updates = et.extract_template_node(state)
    ws = run_dir(state) / "02_template"
    tpl = ws / "标书模板.docx"
    assert updates["template_docx_path"] == str(tpl)

    texts = [p.text for p in Document(str(tpl)).paragraphs]
    assert any("投标函" in x for x in texts)
    assert not any("投标人须知" in x for x in texts)                 # 格式章节之前内容被剪掉
    tpl_md = (ws / "template.md").read_text(encoding="utf-8")
    # 合成样本无 Heading 样式 -> derive_template_md 走扁平列表兜底(标题+表格 stub 均应出现)
    assert "第七章 投标文件的格式" in tpl_md and "【表格】" in tpl_md
    assert (ws / "report.md").exists()
    assert "[2] 第七章 投标文件的格式" in make.calls[0]              # 块化行进 prompt


def test_node_retries_once_with_error_feedback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tender = _tender(tmp_path)
    state = BidState(run_id="run-1", tender_path=str(tender))
    make = _fake_make([{"start_index": 99}, {"start_index": 2}])
    monkeypatch.setattr(et, "make_agent", make)

    et.extract_template_node(state)
    assert len(make.calls) == 2
    assert "错误" in make.calls[1]                                   # 第二次 prompt 带错误反馈


def test_node_raises_after_retry_exhausted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tender = _tender(tmp_path)
    state = BidState(run_id="run-1", tender_path=str(tender))
    make = _fake_make([{"start_index": 99}])
    monkeypatch.setattr(et, "make_agent", make)

    with pytest.raises(et.TemplateExtractError):
        et.extract_template_node(state)
    assert len(make.calls) == 2


def test_node_sidecar_copies_directly_without_llm(tmp_path, monkeypatch):
    """随附权威模板直通复制为底稿,不走 LLM 定界。"""
    monkeypatch.chdir(tmp_path)
    tender = _tender(tmp_path)
    sidecar = tmp_path / "投标模板.docx"
    sd = Document()
    sd.add_paragraph("随附模板正文")
    sd.save(sidecar)
    state = BidState(run_id="run-1", tender_path=str(tender),
                     template_docx_path=str(sidecar))

    def boom(*a, **k):
        raise AssertionError("随附模板存在时不应调用 LLM")
    monkeypatch.setattr(et, "make_agent", boom)

    updates = et.extract_template_node(state)
    ws = run_dir(state) / "02_template"
    assert [p.text for p in Document(str(ws / "标书模板.docx")).paragraphs] == ["随附模板正文"]
    assert (ws / "template.md").exists() and (ws / "report.md").exists()
    assert updates["template_docx_path"] == str(ws / "标书模板.docx")
```

- [ ] **Step 2: 跑红**

Run: `.venv/Scripts/python.exe -m pytest tests/test_node_extract_template.py -v`
Expected: FAIL/ERROR —— 旧模块无 `make_agent` 可 patch、无 `_validate_anchor`、无 `TemplateExtractError`(AttributeError)

- [ ] **Step 3: 重写节点**(src/biaoshu_gen/nodes/extract_template.py 整文件替换)

```python
"""节点 2：投标模板抽取（非 harness）：LLM 定界 + python 剪裁 + 确定性派生 md。

从招标文件中定位"投标文件/响应文件的格式"章节（LLM 只定界），整包副本删区间
剪裁出 标书模板.docx；template.md / report.md 由副本确定性派生，零 LLM。
设计见 docs/superpowers/specs/2026-08-24-extract-template-non-harness-design.md。
"""
import shutil
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from ..docx_io import clip_docx, docx_to_sections, iter_numbered_blocks
from ..models import make_agent, run_sync       # noqa: F401  (测试 monkeypatch et.make_agent)
from ..prompts.extract_template import SYSTEM, build_user_prompt
from ..schemas import TemplateAnchor
from ..state import BidState, run_dir

_RETRY_TIMES = 2   # 首次 + 校验失败重试一次


class TemplateExtractError(RuntimeError):
    """模板抽取失败（LLM 两次输出均未通过校验，或剪裁结果为空）。"""


def _validate_anchor(anchor: TemplateAnchor, n_blocks: int) -> tuple[int, int | None]:
    """硬校验并归一化：(start, end|None) 块序号；end==n 视同 None（到文末）。"""
    s, e = anchor.start_index, anchor.end_index
    if not 0 <= s < n_blocks:
        raise ValueError(f"start_index {s} 越界（共 {n_blocks} 块）")
    if e is not None:
        if e == n_blocks:
            e = None
        elif not s < e < n_blocks:
            raise ValueError(f"end_index {e} 非法（需 start < end < n 或 == n）")
    return s, e


def _extract_from_tender(tender: Path, tpl_docx: Path) -> None:
    """块化 -> 单次 LLM 定界 -> 硬校验（失败带错重试一次）-> 映射元素下标剪裁。"""
    doc = Document(str(tender))
    blocks = iter_numbered_blocks(doc)
    if not blocks:
        raise TemplateExtractError(f"模板抽取失败：{tender} 无任何内容块")
    n_children = len(list(doc.element.body.iterchildren()))
    blocks_text = "\n".join(f"[{b.index}] {b.stub}" for b in blocks)
    agent = make_agent(TemplateAnchor, SYSTEM)

    prompt = build_user_prompt(blocks_text)
    rng: tuple[int, int | None] | None = None
    err = ""
    for _ in range(_RETRY_TIMES):
        anchor: TemplateAnchor = run_sync(agent, prompt).output
        try:
            rng = _validate_anchor(anchor, len(blocks))
            break
        except ValueError as exc:
            err = str(exc)
            prompt = build_user_prompt(blocks_text) + (
                f"\n\n上一次输出未通过校验（错误:{err}），请修正后重新输出。")
    if rng is None:
        raise TemplateExtractError(
            f"模板抽取失败：{tender} 两次输出均未通过校验（最后错误:{err}）")

    s_blk, e_blk = rng
    start_el = blocks[s_blk].element_index
    end_el = blocks[e_blk].element_index if e_blk is not None else n_children
    clip_docx(tender, tpl_docx, start_el, end_el)

    clipped = Document(str(tpl_docx))
    if not any(c.tag != qn("w:sectPr") for c in clipped.element.body.iterchildren()):
        raise TemplateExtractError(f"剪裁结果为空：{tender}（区间 [{start_el},{end_el})）")


def derive_template_md(tpl_docx: Path) -> str:
    """对模板副本确定性派生说明：标题树 + 表格类/文档类标注 + 字数（零 LLM）。"""
    secs = docx_to_sections(tpl_docx)
    titled = [s for s in secs if s.level]
    lines = ["# 响应文件模板说明", "",
             "> 本文件由 标书模板.docx 确定性派生：目录树 + 填写方式标注 + 字数。", ""]
    if not titled:   # 无标题样式退化：列内容块摘要，不报错
        lines += [f"- {b.stub}" for b in iter_numbered_blocks(Document(str(tpl_docx)))]
        return "\n".join(lines) + "\n"
    for s in titled:
        kind = "«表格类»" if "|" in s.content else "«文档类»"
        lines.append("  " * (s.level - 1) + f"- {s.title}（{len(s.content)}字）{kind}")
    return "\n".join(lines) + "\n"


def derive_report_md(tpl_docx: Path) -> str:
    """人读版报告：模板概览与各节字数/表格行一览（零 LLM）。"""
    import re

    sep = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")
    secs = docx_to_sections(tpl_docx)
    titled = [s for s in secs if s.level]
    lines = ["# 响应文件模板抽取报告", "",
             f"- 模板副本：标书模板.docx（{tpl_docx.stat().st_size} 字节）",
             f"- 章节数：{len(titled)}；总字数：{sum(len(s.content) for s in secs)}",
             "", "| 章节 | 层级 | 字数 | 表格行 |", "|---|---|---|---|"]
    for s in titled:
        rows = sum(1 for ln in s.content.splitlines()
                   if ln.strip().startswith("|") and not sep.match(ln.strip()))
        lines.append(f"| {s.title} | H{s.level} | {len(s.content)} | {rows} |")
    return "\n".join(lines) + "\n"


def extract_template_node(state: BidState) -> dict:
    d = run_dir(state)
    ws = d / "02_template"
    ws.mkdir(parents=True, exist_ok=True)
    tpl_docx = ws / "标书模板.docx"

    attached = Path(state.template_docx_path) if state.template_docx_path else None
    if attached and attached.exists():
        shutil.copyfile(attached, tpl_docx)   # 随附权威模板直通，跳过定界与剪裁
    else:
        _extract_from_tender(Path(state.tender_path), tpl_docx)

    (ws / "template.md").write_text(derive_template_md(tpl_docx), encoding="utf-8")
    (ws / "report.md").write_text(derive_report_md(tpl_docx), encoding="utf-8")
    return {"template_docx_path": str(tpl_docx)}
```

- [ ] **Step 4: 跑绿 + 全量回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_node_extract_template.py -v` 然后 `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 新 5 个测试 PASS;全量 PASS(graph/cli 等不受影响——节点函数名未变)

- [ ] **Step 5: 提交**

```bash
git add src/biaoshu_gen/nodes/extract_template.py tests/test_node_extract_template.py
git commit -m "refactor: extract_template 弃用 harness,改 LLM 定界+python 剪裁"
```

---

### Task 4: 清理核查 + 全量回归 + 两份真实样本验收

**Files:**
- Modify: 仅在核查发现残留时微调(预期零或极小 diff)
- 产物: 验收记录写入 SDD 工作区 `task-4-report.md`(不入库)

**Interfaces:**
- Consumes: Task 3 的 `_extract_from_tender`、`derive_template_md`(真实调用需 `.env` 中 llm 三件套配置)
- Produces: 两份真实样本的验收证据(字节量/特征词断言输出)

- [ ] **Step 1: 残留引用核查**

Run: `grep -rn "prepare_workspace\|HarnessTask\|run_harness_task" src/biaoshu_gen/nodes/extract_template.py src/biaoshu_gen/prompts/extract_template.py`
Expected: 无输出(harness 三符号已不在本节点链路;其他节点的使用不在本计划范围)

Run: `grep -rn "has_template_docx\|投标模板参考" src/ tests/`
Expected: 无输出(旧 prompt 符号与随附参考语义已移除;若 tests/ 有残留引用一并清理)

- [ ] **Step 2: 全量回归**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 全部 PASS(基线 128 + 本计划新增约 10 个)

- [ ] **Step 3: 真实样本验收(软件招标文件.docx)**

Run(工作区根目录;.env 已配 llm 三件套):

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe - <<'PY'
from pathlib import Path
from docx import Document
from biaoshu_gen.nodes.extract_template import _extract_from_tender, derive_template_md

name = "软件招标文件"
out = Path(f"data/tender/{name}-标书模板.docx")
_extract_from_tender(Path(f"data/tender/{name}.docx"), out)
texts = [p.text for p in Document(str(out)).paragraphs]
joined = "\n".join(texts)
print("bytes:", out.stat().st_size, "paras:", len(texts))
print("template.md head:\n", derive_template_md(out)[:400])
# 特征断言:格式章节应在、须知/评标办法等非格式章节应不在
assert "投标文件的格式" in joined
assert "投标人须知" not in joined and "评标办法" not in joined
print("ACCEPT OK:", name)
PY
```

Expected: 打印 ACCEPT OK;template.md 树含格式章节子项

- [ ] **Step 4: 真实样本验收(标准的招标文件.docx)**

同 Step 3,`name = "标准的招标文件"`,特征断言改为:

```python
assert "响应文件组成" in joined
assert "磋商邀请" not in joined and "磋商须知" not in joined
print("ACCEPT OK:", name)
```

Expected: 打印 ACCEPT OK;模板含「一、磋商响应声明」至「十二、最后报价」系子项

- [ ] **Step 5: 收尾提交(仅在 Step 1 有清理时)**

```bash
git add -A src/ tests/
git commit -m "chore: 清理 extract_template 非 harness 化后的残留引用"
```

(若 Step 1 即无输出,则本任务无代码改动、无提交——验收记录留在 SDD 工作区即可)
