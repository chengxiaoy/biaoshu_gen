# 无标题样式文档的结构解析兜底设计(LLM 重建)

- 日期:2026-08-24
- 状态:已与需求方确认(对话内呈现设计并获批,方案 B)
- 背景:端到端验收发现一类"不标准格式"招标文件(docx),全文 856 个非空段落中
  Heading 样式为 0,`docx_to_sections` 把整篇切成 1 个 37800 字的 `(前言)` 节,
  关键词路由四组全空,parse 静默产出 4 个空 yaml——不报错,直接污染下游。

## 1. 问题

`docx_io.docx_to_sections` 只依赖 Word Heading 样式(`heading|标题 N`)切节。
样式缺失或形同虚设时:

- 全文归入单个 level=0 `(前言)` 节;
- `classify_sections` 按标题关键词路由,无标题即全空;
- 分组抽取拿到空输入,四个 yaml 输出空结构,**静默失败**。

样本实测(不标准格式招标文件.docx):Heading 段落 0、短加粗段 165、
`第X章` 20 处、中文序号 `一、` 67 处、`X.Y 条款` 186 处——结构信号充足,
只是不在样式里。

## 2. 触发检测(纯代码,docx_io 内)

```python
def needs_structure_fallback(sections: list[DocxSection]) -> bool:
    titled = [s for s in sections if s.level]
    total = sum(len(s.content) for s in sections)
    return len(titled) < 3 or (titled and total / len(sections) > 8000)
```

- 标题节数 <3 → "明显过少";
- 平均节长 >8000 字 → "不正确"(标题存在但形同虚设);
- 正常文档只多一次内存统计,零开销。

## 3. LLM 结构重建(nodes/structure.py,新模块)

1. **块化**:`iter_numbered_blocks(doc)` 按文档顺序给段落/表格编号 `[0]…[N]`;
   表格压成一行摘要(`[12]【表格】首行内容…`),856 段 + 16 表 stub 约 2 万字,单次调用可容纳。
2. **一次 PydanticAI 结构化调用**(走现有 llm 三件套):prompt 给出标书章节惯例
   (`第X章`→1 级、数字序号→2 级、`（一）`/`X.Y`→3 级),返回
   `list[Heading{index, level≤3, title}]`;明确指示目录页/封面区条目不算章节标题
   ——语义去 TOC 是选 LLM 方案的核心原因。
3. **代码侧校验**(不信模型):index 单调递增否则丢弃违规项、title 非空且 ≤50 字、
   首个标题强制 level 1、level 夹在 1~3;校验失败带错误信息重试一次。
4. **本地切分**:内容永远从原 docx 块取,LLM 只决定边界——幻觉最多切错位置,
   不会编造内容。首个标题前归 `(前言)` 节,与现状一致。

## 4. 组件边界与数据流

- `docx_io.py` 保持纯函数:新增 `needs_structure_fallback()` 与 `iter_numbered_blocks()`,
  不引入任何 LLM 依赖。
- `nodes/structure.py`:编排 + prompt + 校验 + 切分;agent 以参数注入,便于单测换假模型。
- `nodes/parse_tender.py` 增加三行:检测→触发则 `rebuild_sections(...)`→其余不变;
  routing.yaml 增加 `structure_mode: heading | llm_rebuild` 一行留痕。
- 下游(routing/tender.md/分组抽取/template/outline)零改动,消费的仍是 `list[DocxSection]`。

## 5. 错误处理

LLM 调用失败(含校验重试后再失败)即响亮报错,parse 停在该节点,重跑同一命令从
checkpoint 续跑——与现有断点续跑哲学一致;杜绝静默空 yaml。

## 6. 测试(TDD)

- 检测阈值:全无标题 / 正常文档 / 标题稀疏三种 fixture。
- 校验逻辑:乱序 index、超长 title、非法 level 各单测。
- 切分正确性:给定假 Heading 边界,断言 DocxSection 内容归属。
- parse 节点集成:注入假 agent,routing.yaml 含 `structure_mode: llm_rebuild`。
- 真实验收:用不标准格式招标文件.docx 手动跑 `biaoshu parse`,
  四组路由命中、四个 yaml 非空。

## 7. 明确不做(YAGNI)

- assemble 侧 `docx_block_ranges` 的同类兜底(响应模板是另一类文档,本次样本未覆盖);
- 把重建结果回写 docx Heading 样式(内存中构建 DocxSection 即够下游使用);
- 多次 LLM 调用迭代细化层级(单次 + 代码校验重试一次封顶)。
