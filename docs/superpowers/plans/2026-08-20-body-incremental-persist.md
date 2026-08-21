# body 小节即时落盘实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** body 每个小节生成后立即落盘,任意中断后重跑 `biaoshu body` 自动复用已有文件、只补缺失小节。

**Architecture:** 把写盘从"全部完成后批量写"挪进并发 worker `gen()` 内(run_sync 返回即写);复用读入路径(`reuse_existing`)已存在,不动。spec 见 `docs/superpowers/specs/2026-08-20-body-incremental-persist-design.md`。

**Tech Stack:** Python 3.11+ · ThreadPoolExecutor · pydantic-ai FunctionModel(测试)· pytest

## Global Constraints

- 不新增依赖、不改 `gen()` 对外行为(返回 `(leaf, SectionBody)` 不变)。
- 测试命令用 `.venv/Scripts/python.exe -m pytest`(bash 无 poetry)。
- 回环修复路径与 `body.md` 拼装行为不变。
- 既有 body 测试全部保留不改语义。

---

### Task 1: gen() 内即时落盘

**Files:**
- Modify: `src/biaoshu_gen/nodes/body.py:69-85`(`gen()` + 批量写循环)
- Test: `tests/test_node_body.py`(末尾追加)

**Interfaces:**
- Consumes: 无。
- Produces: `gen()` 副作用变更--每个小节 LLM 返回后其文件立即出现在 `05_body/`;`body_node` 不再在收尾处批量写。

- [ ] **Step 1: 写失败测试**

`tests/test_node_body.py` 顶部补 `import pytest`(现无),末尾追加:

```python
def test_body_writes_each_leaf_immediately(tmp_path: Path, monkeypatch):
    """小节生成即落盘：某小节生成失败（模拟中断）时，已完成的已在盘上。"""
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)

    def make(output_type, system_prompt, retries=2):
        async def fn(messages, info: AgentInfo):
            prompt = _last_user_content(messages)
            if "质量保障" in prompt:            # 2.2 中途失败
                raise RuntimeError("模拟中断")
            out = {"title": "占位", "content": OK_CONTENT}
            return ModelResponse(parts=[ToolCallPart(
                tool_name=info.output_tools[0].name, args=json.dumps(out))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(body_mod, "make_agent", make)
    with pytest.raises(RuntimeError):
        body_mod.body_node(state)

    d = run_dir(state) / "05_body"
    for name in ("1.1-背景现状.md", "1.2-建设思路.md", "2.1-进度安排.md"):
        assert (d / name).exists(), name      # 旧实现：批量写在最后，一个文件都不会有
    assert not (d / "2.2-质量保障.md").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_node_body.py::test_body_writes_each_leaf_immediately -v`
Expected: FAIL--`assert (d / '1.1-背景现状.md').exists()` 失败(批量写未执行,ex.map 异常直接抛出,盘上无文件)。

- [ ] **Step 3: 最小实现**

`src/biaoshu_gen/nodes/body.py`--`gen()` 末尾加立即落盘,并删除收集后的批量写循环:

```python
    def gen(leaf: OutlineNode) -> tuple[OutlineNode, SectionBody]:
        f = _leaf_file(d, leaf)
        if reuse_existing and f.exists():
            return leaf, SectionBody(title=leaf.title, content=f.read_text(encoding="utf-8"))
        snippets = kb.search(f"{leaf.title} {leaf.description}")
        kb_text = "\n\n".join(f"【{c.source.name}】\n{c.text}" for c in snippets) or "（无）"
        result = run_sync(agent, build_user_prompt(
            sec_id=leaf.id, title=leaf.title, description=leaf.description,
            target_words=leaf.target_words, tree=tree, facts=facts_text, kb=kb_text,
            feedback=state.body_feedback if leaf.id in fix_ids else "",
        )).output
        f.write_text(result.content, encoding="utf-8")   # 即时落盘：中断后重跑只需补缺
        return leaf, result
```

删除 `body.py:84-85`:

```python
    for leaf, res in results:
        _leaf_file(d, leaf).write_text(res.content, encoding="utf-8")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_node_body.py -v`
Expected: PASS(10 个,含既有全部)。

- [ ] **Step 5: 全量回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 104 passed。

```bash
git add src/biaoshu_gen/nodes/body.py tests/test_node_body.py
git commit -m "perf: body 小节即时落盘，中断后重跑自动续缺"
```
