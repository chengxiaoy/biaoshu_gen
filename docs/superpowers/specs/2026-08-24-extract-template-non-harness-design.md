# extract_template 非 harness 化设计(LLM 定界 + python 剪裁)

- 日期:2026-08-24
- 状态:已与需求方确认(设计获批;锚点算法由需求方指定改回 LLM 定界)
- 背景:extract_template 节点当前用 harness 子进程代理产出 标书模板.docx /
  template.md / report.md。性能和稳定性差:代理逐文件探查、多轮试错。
  该节点本质是找出格式章节在招标文档中的起止边界,再剪裁出副本。

## 0. 需求方决策记录

| 决策点 | 结论 |
|---|---|
| 锚点定位 | **LLM 定界 + 代码硬校验**(需求方指定;复用结构兜底"LLM 只定界"模式) |
| docx 剪裁 | 整包副本删区间(保样式/编号/页眉页脚) |
| template.md / report.md | 全确定性派生,零 LLM |
| 锚点/校验失败 | 响亮报错 TemplateExtractError,checkpoint 续跑 |
| 随附响应模板 docx 存在时 | 直接 copyfile 用作底稿,跳过剪裁 |

## 1. 问题

`nodes/extract_template.py` 经 `run_harness_task` 派发 claude-agent-sdk 子进程,
让代理读 tender.md 与 招标文件.docx 自行探索并产出三件产物:

- 慢且不稳:harness 逐段探查与试错开销大(参照 fill 阶段慢因分析);
- 格式章节的截取质量依赖代理自觉,偶发漏截/多截无硬校验。

下游契约(必须保持):节点返回 `{"template_docx_path": str(tpl_docx)}`,
facts / fill_forms / deviation_table / commercial / assemble 均以该副本为格式底稿;
review 读 `02_template/template.md`;cli status 列该文件。

## 2. 组件边界

- **`docx_io.py`(保持纯函数,不引入 LLM)**:
  - `NumberedBlock` 增加 `element` 与 `element_index` 字段(带默认值,
    手工构造的既有测试不受影响):body 子元素引用与其下标,供剪裁映射;
    `iter_numbered_blocks` 改为沿 body 子元素遍历计数(跳空段但计数连续)。
  - 新增 `clip_docx(src, dest, start_index, end_index)`:
    shutil.copyfile → 打开副本 → 删除 `[0,start)` 与 `[end,)` 区间外 body 子元素
    (sectPr 固定保留)→ 保存。end_index 可传 len(children) 表示到文末。
- **`schemas.py`**:新增 `TemplateAnchor{start_index:int, end_index:int|None=None}`
  (end_index=None 表示格式章节到文末),插在 StructureOutline 之后。
- **`prompts/extract_template.py`**(整文件重写):SYSTEM + TEMPLATE——给出全部
  `[i] stub` 行,要求返回 `{"start_index": …, "end_index": …|null}`;
  规则:start=「投标文件的格式/响应文件的组成」类格式章节标题块;
  end=其后下一个章级标题块;目录页条目不算;花括号转义。
- **`nodes/extract_template.py`**(重写,harness 调用全移除):
  LLM 定界 + 校验 + clip + 确定性派生 md;新增 `TemplateExtractError(RuntimeError)`。

## 3. 锚点算法(LLM 定界 + 硬校验)

```
① blocks = iter_numbered_blocks(doc)          # 表格压 stub,编号连续
② 单次 PydanticAI 调用(make_agent/run_sync,llm 三件套)
   返回 TemplateAnchor{start_index, end_index|null}
③ 硬校验(不信模型):
   start ∈ [0, n);end 为 None 或 start < end ≤ n(end==n 视同"到文末");
   失败带具体错误重试一次(rebuild_sections 同款);再失败抛 TemplateExtractError
④ 剪裁映射:
   start_el = blocks[start].element_index
   end_el   = blocks[end].element_index(start<end<n 时)
            = len(children)(end 为 None 或 end==n)
   clip_docx(tender_path, tpl_docx, start_el, end_el)
```

收益:零标题样式文档同样适用(无需正则兜底支路);prompt 无需打分启发式。

## 4. 数据流与产物

1. 随附模板(`state.template_docx_path` 初值非空且存在)→ copyfile 直通为
   `标书模板.docx`,跳过 LLM 与剪裁。
2. 否则按第 3 节剪裁生成;剪裁后校验副本 body 至少一个元素,空则报错。
3. `template.md`(确定性派生):对 标书模板.docx 跑 `docx_to_sections`,
   输出标题树(层级缩进)+ 每节标注(`«表格类»` 含表格 / `«文档类»` 纯文字)+
   字数;头部注明依据来源。无标题节时退化为块列表(不报错)。
4. `report.md`(确定性派生):同源信息人读版(目录树、各节表格数/字数一览表)。
5. 返回值契约不变:`{"template_docx_path": str(tpl_docx)}`。

## 5. 错误处理

- LLM 调用失败、校验重试后再失败、剪裁结果为空 → 抛 `TemplateExtractError`,
  parse 停在该节点,重跑同一命令从 checkpoint 续跑(与 StructureError 同哲学),
  杜绝静默错误底稿污染下游。
- 性能:至多一次 LLM 结构化调用(重试一次封顶),零子进程。

## 6. 测试(TDD)

- **docx_io 单测**(合成 fixture):
  - NumberedBlock.element_index 计数正确(跳空段计数连续);
  - clip_docx 保留 [start,end)、sectPr 幸存、区间外删除;
  - 「第七章 格式」+ 后随「第八章」→ 区间不含第八章;格式章节到文末 → 到 sectPr 前。
- **节点单测**(monkeypatch make_agent 注入假模型,structure 测试同款):
  - 合法 anchor → 三产物齐、template.md 含目录树标记;
  - 首次非法+重试合法 → 成功;两次非法 → TemplateExtractError;
  - 随附模板存在 → 不调 LLM 直接复制;
  - 剪裁出的副本不含格式章节之前内容(如「投标人须知」正文特征)。
- **真实验收**:`data/tender/软件招标文件.docx` 与 `标准的招标文件.docx` 各跑一次
  节点级脚本:标书模板.docx 非空、含格式特征(投标函/偏离表等)、
  不含非格式章节内容;template.md 目录树完整。

## 7. 明确不做(YAGNI)

- assemble 侧 `docx_block_ranges` 的 w:ins 同款隐患(待另开单);
- 把锚点结果回写招标文档 heading 样式;
- 多轮 LLM 迭代细化边界(单次 + 重试一次封顶);
- template.md/report.md 的语义摘要(份数、签署要求等文字归纳不做,仅结构信息)。
