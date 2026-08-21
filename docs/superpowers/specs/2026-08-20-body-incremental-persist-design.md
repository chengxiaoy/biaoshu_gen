# body 小节即时落盘与自动续跑设计

- 日期:2026-08-20
- 状态:已与需求方确认(对话内呈现设计并获批)
- 背景:端到端验收中 body 阶段被中止,85 个小节全部完成前不落盘,已生成内容全部丢失,重跑从头再来。

## 1. 问题

`nodes/body.py` 现状:并发 `gen()` 生成小节 -> 结果攒内存 -> **全部完成后**统一写盘(`body.py:84-85`)。进程中途退出(被杀/崩溃/网络中断后放弃)时磁盘上一个小节都没有。

复用端已存在:重跑时 `reuse_existing=True`,已存在的叶子文件直接读盘跳过 LLM(`body.py:64,71-72`,注释即"崩溃续跑")。缺口只在写出端。

## 2. 改法

把写盘挪进 `gen()`--每个小节 `run_sync` 返回后立即写自己的文件;删除收集后的批量写循环:

```python
def gen(leaf: OutlineNode) -> tuple[OutlineNode, SectionBody]:
    f = _leaf_file(d, leaf)
    if reuse_existing and f.exists():
        return leaf, SectionBody(title=leaf.title, content=f.read_text(encoding="utf-8"))
    ...
    result = run_sync(agent, ...).output
    f.write_text(result.content, encoding="utf-8")    # 新增:立即落盘
    return leaf, result
```

- 各工作线程写各自独立文件,无共享冲突。
- `body.md` 拼装仍用内存中的 results,不受影响。
- 回环修复路径(`fix_ids`,`reuse_existing=False`)同样即时落盘,行为不变。

## 3. 效果与验收

- body 任意时刻中断,已完成小节已在 `05_body/` 盘上;重跑 `biaoshu body` 自动复用已有文件、只补缺失小节(无需新状态文件,复用现有 `reuse_existing` 逻辑)。
- 测试(新增于 `tests/test_node_body.py`):部分小节已有文件时重跑,已完成小节不触发 LLM 调用、缺失小节补齐、`body.md` 拼装完整。
- 既有 body 测试全部保留不改语义。

## 4. 明确不做(YAGNI)

- 小节级 checkpoint 状态文件 / 中断进度报告--文件存在性即状态。
- 跨阶段的中断恢复机制(仅 body 阶段)。
