# 软件标书智能体 POC 设计文档

- 日期：2026-08-18
- 状态：已与需求方逐节确认
- 上游依据：飞书文档《软件标书智能体方案规划》（docx: Ut8VdKFxdoZC6YxBHXscxpwzn9b）

## 1. 背景与目标

构建软件标书智能体 POC：输入招标文件（docx）与企业信息知识库，自动解析招标文件、生成符合投标要求的标书草稿（docx）。

POC 验收形态：**端到端可跑通**——用仓库 `docs/` 中的样例素材（`软件招标文件.docx`、`标书模板.docx`、`营业执照测试.jpg`）真实产出一份标书草稿。

### 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 完成度 | 端到端可跑通的骨架，节点为真实实现 |
| 编排 | 单一 LangGraph 全流程状态图 + SqliteSaver checkpoint 分阶段执行 |
| 非 harness 节点 | PydanticAI，模型 DeepSeek `deepseek-chat`（OpenAI 兼容端点，`DEEPSEEK_API_KEY` 放 `.env`） |
| harness 节点 | Claude Code SDK（`claude-agent-sdk`），继承本机智谱 Anthropic 兼容网关凭证 |
| 用户交互 | 分阶段 CLI 子命令，中间产物落盘为 YAML/Markdown 供用户编辑后续跑 |
| 企业知识库 | 本地目录 + jieba 分词 + BM25 关键词检索，不做向量 RAG |
| 招标解析读取方式 | docx 按标题切章节；先用仅含目录行的分类调用把章节路由到四组信息；再按组拼接章节内容分别抽取，避免整篇长上下文 |
| 全局事实的依赖 | 全局事实设定依赖标书元数据 + 评价标准（与上游状态图一致） |
| 依赖管理 | poetry |
| 数据存储 | 本地文件系统 |
| 运行方式 | 本地命令行 |

## 2. 架构总览

```
CLI (typer)  ──子命令──▶  LangGraph StateGraph（单图 = 文档全局流程图）
                              │  State: BidState (Pydantic)  checkpoint: SqliteSaver
                              │
              ┌───────────────┴────────────────┐
        非 harness 节点                    harness 节点
        PydanticAI + DeepSeek              Claude Code SDK（继承智谱网关凭证）
        （结构化输出）                      （文件操作型 agent：填表/抽取/审核/修改）
```

- 一张 `StateGraph` 严格按照上游文档的 Mermaid 全局流程图连边，包括 **审核不通过 → 修改 → 再审核** 的条件回边。
- 每个 CLI 子命令 = 从上次 checkpoint 恢复，用 `interrupt_after` 跑到指定阶段后停下；同一条命令重跑即从断点续跑。
- 企业知识库由 `kb.py` 加载：文本类文件做 jieba 分词 + BM25 检索供 PydanticAI 节点引用；图片类材料（如营业执照）只登记路径，供 harness 节点直接查看。

## 3. 节点清单（对应全局流程图）

| # | 节点 | 类型 | 输入 → 输出 |
|---|---|---|---|
| 1 | `parse_tender` | PydanticAI | 招标文件 docx 按标题分节 → 目录分类（仅标题行进入分类调用）→ 按组拼接章节内容分别抽取 → 标书元数据 / 标书需求 / 废标扣分项 / 评标标准（四组 Pydantic schema）；单组超长再按整节分批抽取后代码侧合并 |
| 2 | `extract_template` | harness | 招标文件 → 响应文件模板（目录树 + 每节填写要求，`template.md`）+ 标书目录报告（`report.md`） |
| 3 | `facts` | PydanticAI | 元数据 + 评分标准 → 全局事实设定（工期/人员配置/软件指标），落盘 `facts.yaml` 供用户编辑 |
| 4 | `outline` | PydanticAI | 需求 + 技术评分标准 + 事实 → 章节目录 + 各节预期字数，落盘 `outline.yaml` |
| 5 | `body` | PydanticAI | 目录 + 事实 + KB 检索片段 → 逐章正文（循环子步骤，拼成 `body.md`） |
| 6 | `body_review` | PydanticAI | 正文 + 事实 + 废标扣分项 → 检验报告；有问题带意见回 `body`（限 2 轮） |
| 7 | `fill_forms` | harness | 模板 + 元数据 + KB → 投标函 / 报价文件 / 货物一览表 / 资格证明（docx 填空） |
| 8 | `deviation_table` | harness | 模板 + 需求 + 评分标准 → 偏离表 docx |
| 9 | `commercial` | harness | 模板 + KB + 事实 → 商务响应 docx |
| 10 | `assemble` | 纯代码 | 模板 docx + body.md + 7/8/9 产物 → 标书草稿 docx（版本号管理） |
| 11 | `review` | harness | 草稿 + 招标文件 + 事实 + KB → 审核意见（废标扣分项/事实一致性/引用项/材料齐全/格式 五项检查） |
| 12 | `revise` | harness | 审核意见 + 草稿 → 修改后草稿（新版本号），回 `review`（限 2 轮） |

技术方案生成（节点 3–6）即上游文档中的状态图：全局事实设定 → 目录生成 → 正文生成 → 审核检验（不通过回正文生成）。

## 4. 数据流与目录布局

```
data/
├── tender/软件招标文件.docx          # 招标文件（POC 用 docs/ 样例）
├── company/                          # 企业信息知识库（POC 用 docs/ 样例材料）
└── runs/<run_id>/
    ├── checkpoint.sqlite              # LangGraph 状态（断点续跑）
    ├── error.log                      # 最近一次错误
    ├── 01_parse/   metadata.yaml / requirements.yaml / scoring.yaml / invalidation.yaml
    ├── 02_template/  template.md（响应文件模板+目录）/ report.md
    ├── 03_facts.yaml                 # ← 用户人工控制点 1（可编辑后继续）
    ├── 04_outline.yaml               # ← 用户人工控制点 2（可编辑后继续）
    ├── 05_body/   01-章节.md ... body.md
    ├── 06_fill/   forms/forms.docx、deviation/deviation.docx、commercial/commercial.docx
    │              （三 harness 节点并行执行，工作区按子目录隔离）
    ├── 07_draft/  标书草稿_v1.docx、标书草稿_v2.docx…（latest.txt 记录当前版本）
    └── 08_review/ review_round_N.md
```

- 用户人工控制点：`03_facts.yaml`（改全局事实）与 `04_outline.yaml`（改章节/字数）。用户编辑后执行下一条子命令，节点重新读取并校验该文件，用户修改优先于模型重生成（对应上游文档"用户可以输出观点和精细控制"）。
- 标书草稿版本：`assemble` / `revise` 产出 `标书草稿_vN.docx`，`07_draft/latest.txt` 记录当前版本号，`revise` 基于最新版本修改。

## 5. CLI 设计（typer）

子命令（每个 = 恢复 checkpoint 跑到对应阶段）：

```
biaoshu init --tender <docx> --kb <dir> [--run-id <id>]   # 创建 run 目录与初始 state
biaoshu parse        # → 节点 1 后中断
biaoshu template     # → 节点 2 后中断
biaoshu facts        # → 节点 3 后中断（产物供人工编辑）
biaoshu outline      # → 节点 4 后中断（产物供人工编辑）
biaoshu body         # → 节点 5+6（含内循环）完成后中断
biaoshu fill         # → 节点 7/8/9 完成后中断
biaoshu assemble     # → 节点 10 后中断
biaoshu review       # → 节点 11 后中断
biaoshu revise       # → 节点 12（含回环至收敛）后结束
biaoshu status       # 查看当前 run 进度与产物清单
biaoshu run --all    # 全自动一口气跑完（冒烟用）
```

- 除 `init` 外所有子命令接受 `--run-id`（默认取最近创建的 run）。
- `fill` 阶段的 7/8/9 三个 harness 节点并行执行（LangGraph fan-out）。

## 6. 工程结构

```
pyproject.toml                     # poetry
.env                               # DEEPSEEK_API_KEY（已有智谱凭证走环境继承，无需写入）
data/                              # 运行数据（git 忽略 runs/）
docs/                              # 样例素材 + 本设计文档
src/biaoshu_gen/
├── cli.py                         # typer 入口
├── config.py                      # pydantic-settings：模型、路径、限额（重试次数/回环上限）
├── state.py                       # BidState（Pydantic）
├── schemas.py                     # 各节点输出 schema（元数据/需求/评分/事实/目录/审核意见）
├── models.py                      # PydanticAI Agent 工厂（DeepSeek）
├── harness.py                     # Claude Code SDK 封装：任务下发、产物校验、重试
├── kb.py                          # 知识库加载 + jieba/BM25 检索
├── docx_io.py                     # docx 文本/表格提取、模板填充、草稿写出
├── graph.py                       # StateGraph 构建（含条件回边与 interrupt 点）
├── nodes/                         # 每节点一个模块
│   ├── parse_tender.py  extract_template.py  facts.py  outline.py
│   ├── body.py  body_review.py
│   ├── fill_forms.py  deviation_table.py  commercial.py
│   └── assemble.py  review.py  revise.py
└── prompts/                       # 每节点 prompt 一个 Python 模块（上游文档要求）
    ├── parse_tender.py  extract_template.py  facts.py  outline.py
    ├── body.py  body_review.py
    ├── fill_forms.py  deviation_table.py  commercial.py
    └── review.py  revise.py          # assemble 为纯代码节点，无 prompt 模块
tests/
├── test_schemas.py  test_kb.py  test_docx_io.py  test_graph.py  test_cli.py
└── test_nodes_fake_model.py  test_harness_mock.py
```

依赖：`langgraph`、`langgraph-checkpoint-sqlite`、`pydantic-ai`、`claude-agent-sdk`、`typer`、`python-docx`、`jieba`、`rank-bm25`、`pyyaml`、`pydantic-settings`；开发依赖：`pytest`。

## 7. 错误处理

- **LLM 输出校验失败**：PydanticAI `retries=2` 自动带校验错误重试；仍失败则节点抛异常，CLI 非零退出并写 `runs/<run_id>/error.log`。
- **DeepSeek / Claude SDK 调用失败**：`models.py` / `harness.py` 统一捕获网络/超时/限流，指数退避重试 2 次；最终失败保留 checkpoint，重跑同一子命令从断点续跑。
- **harness 产物校验**：每个 harness 节点与 SDK 约定"完成后必须产出哪些文件"，节点检查文件存在且非空；缺失则反馈缺项重试一次，再失败才报错。
- **回环上限**：`body_review → body` 限 2 轮、`review → revise` 限 2 轮；达到上限不再回环，遗留问题写入审核报告末尾（标注"需人工处理"），流程继续——对应上游文档"结束，人工审核签字"的人工接管点。
- **字数控制**：`body_review` 校验各章节实际字数 vs outline 目标（±20% 容差），超差章节随回环意见重生成；两轮后仍超差则告警不阻塞。
- **Windows 兼容**：全部 `pathlib` + UTF-8；子进程显式 `encoding="utf-8"`；路径含中文不假设 ASCII。
- **用户编辑产物被改坏**：`facts.yaml` / `outline.yaml` 在下阶段启动时用 Pydantic 重新校验，失败给出字段级错误提示，不静默覆盖用户修改。

## 8. 测试策略

- **单元测试（pytest，无 LLM 成本）**：schemas 校验边界；kb 加载与中文检索排序；docx_io 用合成 docx fixture 做提取/填充往返；graph 节点集合与邻接关系（含两条条件回边、interrupt 点）；CLI 参数与 run 目录创建、status 输出。
- **LLM 节点测试**：PydanticAI `TestModel`/`FunctionModel` 假模型驱动节点，验证 prompt 组装、schema 输出解析、失败重试路径。
- **harness 节点测试**：mock `harness.py` 的 SDK 调用，验证任务 prompt 组装、产物存在性校验、缺文件重试。
- **端到端冒烟（手动，不进自动测试）**：`biaoshu run --all`，真实调 DeepSeek + Claude Code SDK，产出 `07_draft/标书草稿_v1.docx`——POC 最终验收手段。

## 9. 验收标准

1. `poetry install` 后 `biaoshu --help` 可用，子命令注册齐全。
2. 分阶段子命令在样例招标文件上跑通，产物按第 4 节目录落盘；`facts.yaml`/`outline.yaml` 人工编辑后能被后续阶段正确读取（用户修改优先）。
3. `run --all` 一条命令端到端产出标书草稿 docx（模板结构 + 技术方案正文 + 已填表格 + 偏离表 + 商务响应），审核报告生成且废标项检查结果可见。
4. pytest 全绿（单测 + mock 测试），无 LLM 依赖也能跑。
5. 审核/修改回环按上限收敛，不无限循环。

## 10. 范围外（POC 不做）

- 前端界面、Web 服务、数据库（上游文档明确 POC 不实现）。
- 向量 RAG / embedding 检索（上游进度表列为后续计划）。
- 多招标文件批量处理、并发多 run 调度。
- 造价/报价测算（报价文件仅做模板空格填充，不生成报价数字策略）。
