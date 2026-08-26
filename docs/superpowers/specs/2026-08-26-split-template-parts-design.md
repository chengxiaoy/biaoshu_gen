# 响应模板四分拆设计(fill 前置拆分)

日期:2026-08-26 | 来源:docs/feedbacks.md 第 64 行未勾项

## 背景与目标

fill 三节点(forms/deviation/commercial)目前各自复制**整份**标书模板副本操作,
assemble 再靠锚点区间替换合并。问题:每节点上下文冗余(173KB 全模板)、合并侧
需要锚点匹配/去重兜底等复杂机制。目标:template 阶段后把响应模板拆成四部分,
fill 各用各的 part,assemble 退化为**顺序拼接**。

## 决策记录(用户裁决)

| 决策点 | 选择 |
|---|---|
| 拆分落点 | template 阶段后新增拆分步(02_template/parts/ + parts.yaml) |
| 下游接入 | 全量改接(三 fill 节点 + assemble 重写) |
| 边界判定 | 确定性规则优先,无标题模板 LLM 兜底 |

## 四 bucket 与归类规则(按序命中,先到先得)

| bucket | 文件名 | 规则(标题含关键词) |
|---|---|---|
| deviation | 偏离表部分.docx | 偏离 |
| technical | 技术方案部分.docx | 实施方案/技术方案/技术部分 |
| forms | 表格填写部分.docx | 投标函/响应声明/报价/价格/一览表/开标/资格 |
| commercial | 商务填写部分.docx | **其余一律**(catch-all:保证金/政策优惠/类似业绩…) |

## 组件

1. **docx_io.clip_docx_keep(src, dest, keep_ranges)**:整包副本删多区间之外元素
   (sectPr 永留)。与 clip_docx 同族,多区间保留版。
2. **nodes/split_template.py**(新节点,STAGES["template"] 成员扩为
   (extract_template, split_template),end_nodes 同步):
   - 有标题:沿 body 走块,Heading 段切 current title → 按规则归 bucket,记录元素区间
   - 无标题(未命中任何 Heading):LLM 兜底——iter_numbered_blocks stubs 单次
     PydanticAI 调用输出 spans([{start_index,end_index|None,bucket}]),硬校验
     (界内/bucket 合法/不重叠),失败带错重试一次封顶;未覆盖块 → commercial
   - 产出四份 part docx + parts.yaml({parts: {bucket: {path,sections,first_element_index}}, order})
   - state 新增 template_parts: dict[str, str];空 bucket 不落文件(path=""),fill 回退整模板
3. **fill_context.run_fill_node(part=...)**:工作区 标书模板.docx 改为复制对应
   part(state.template_parts 有且文件存在),缺失回退整模板;gate 判定同源。
   deviation/forms/commercial 分别传 deviation/forms/commercial。
4. **nodes/assemble.py 重写(主路径)**:parts.yaml 存在时——新建草稿,按
   first_element_index 排序各 part:technical 注入 body(锚定技术区间,无锚追加),
   其余桶取已填充产物(fill 节点输出,跳过则用原始 part)整段追加。**锚点匹配/
   去重兜底退役**,仅保留无 parts.yaml 时走旧逻辑(老 run 回退)。

## 错误处理

- LLM 兜底两次校验失败 → 响亮报错(与 TemplateExtractError 同款语义)
- 某 bucket 空 → 不产文件,fill 回退整模板,assemble 跳过
- parts.yaml 缺失(老 run)→ fill/assemble 全部回退旧路径

## YAGNI

- 不做跨 bucket 重排、不做 part 级 checkpoint
- review/revise 契约不变(仍面对 07_draft 整稿)
- 不改 fill 各节点 prompt(工作区文件名仍为 标书模板.docx)

## 测试策略

clip_docx_keep 多区间/sectPr;split 有标题归类/parts.yaml/state;无标题 LLM 兜底
与重试;fill 用 part 与回退;assemble 顺序拼接与回退;STAGES 拓扑断言。
