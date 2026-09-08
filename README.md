# biaoshu_gen —— 软件标书智能体 POC

上传招标文件（docx）与企业知识库，自动解析招标要求并生成投标文件草稿。
设计文档：`docs/superpowers/specs/2026-08-18-biaoshu-agent-poc-design.md`

## 技术栈

Python 3.11+ · poetry · LangGraph（单一状态图 + SqliteSaver 断点续跑）·
PydanticAI（结构化输出节点，OpenAI 协议端点：OpenRouter / DeepSeek 等）·
Claude Code SDK（harness 文件操作节点，独立 HARNESS_* 三件套注入 Anthropic 协议端点）

## 安装

```bash
poetry install
cp .env.example .env   # 写入两套三件套：API_KEY/MODEL_NAME/BASE_URL（OpenAI 协议）
                        # + HARNESS_API_KEY/HARNESS_BASE_URL/HARNESS_MODEL（Anthropic 协议）
```

## 数据准备

```bash
# 招标文件与企业知识库示例已放于 data/tender/ 与 data/company/，可直接使用
# 可选：放入响应文件模板 *模板*.docx（biaoshu init 会自动发现 data/tender/ 下的模板）
cp docs/标书模板_软件.docx data/tender/标书模板.docx
```

## 分阶段使用（人工控制点：03_facts.yaml / 04_outline.yaml 可编辑后续跑）

```bash
poetry run biaoshu init --tender data/tender/服务招标文件.docx --kb data/company
poetry run biaoshu parse      # 招标解析（按目录分节阅读）→ 01_parse/
poetry run biaoshu template   # 响应模板抽取（harness）→ 02_template/
poetry run biaoshu facts      # 全局事实 → 03_facts.yaml（可人工编辑）
poetry run biaoshu outline    # 技术方案三级目录 → 04_outline.yaml（可人工编辑）
poetry run biaoshu body       # 按三级小节并发生成正文（并发数 BODY_CONCURRENCY，默认 6）
                             #   + 审核检验（≤2 轮回环，仅重写有问题的小节）→ 05_body/
poetry run biaoshu fill       # 三表并行填写（harness）→ 06_fill/
poetry run biaoshu assemble   # 拼装草稿 → 07_draft/标书草稿_v1.docx
poetry run biaoshu review     # 全面审核（harness）→ 08_review/
poetry run biaoshu revise     # 按意见修改并跑完循环（≤2 轮）
poetry run biaoshu status     # 查看进度
```

全自动（冒烟）：`poetry run biaoshu run`

## 重跑某个阶段（rerun）

每个阶段完成时都会备份 checkpoint 到 `data/runs/<run>/checkpoints/<stage>.sqlite`，
`rerun` 回退到**该阶段开始前**的状态并重跑——典型场景：对某阶段产物不满意、
修改了阶段代码后想用新代码重新生成。

```bash
# 例：parse 产物不满意，修改解析代码后重跑（其余阶段产物不受影响）
poetry run biaoshu rerun parse

# 重跑指定 run 的某阶段（默认取最近一次 run）
poetry run biaoshu rerun outline --run-id run-20260904-101500
```

行为说明：
- **中间阶段**（template 及之后）：回退到其**前一个阶段完成时**的 checkpoint 再重跑，
  该阶段之后产生的状态被丢弃
- **parse 是首个阶段**，没有前序 checkpoint：直接清空当前进度从头重跑
- **rerun 会先删除该阶段的产物**再重跑（如 `rerun facts` 删 `03_facts.yaml`、`rerun body` 删 `05_body/`）——因为 facts/outline 等节点「产物存在即跳过」；注意若被重跑的阶段产物正是你手工编辑过的控制点文件（03_facts.yaml/04_outline.yaml），编辑内容会随重跑消失，请先自行备份
- 重跑后想继续往下走：直接执行后续阶段命令即可（未重跑的阶段若已完成会被跳过；
  若要从中间恢复，`rerun <后续阶段>` 会先回退到其前序备份再执行）
- 本地开发的产品知识库是固定 dataset（`RAGFLOW_DATASET_NAME`），`rerun parse`
  不会重复上传——同名文件在 init/载入时自动跳过

## 真实模型端到端测试（验收用）

不花 LLM 成本的单元测试见下节；本节是**接入真实模型与真实 harness 的完整验收流程**
（已在 Windows 11 + OpenRouter `deepseek/deepseek-v4-flash-0731` 跑通）。

### 1. 配置 `.env`（两套三件套，各自协议独立）

```ini
API_KEY=sk-你的key            # OpenRouter / DeepSeek 官方等
MODEL_NAME=deepseek/deepseek-v4-flash-0731
BASE_URL=https://openrouter.ai/api/v1     # 写完整 …/chat/completions 也可以，会自动归一

HARNESS_API_KEY=sk-你的harness-key    # Anthropic 协议端点 key（智谱 / Anthropic 官方 / OpenRouter 等）
HARNESS_BASE_URL=https://open.bigmodel.cn/api/anthropic   # 写 …/v1 或 …/v1/messages 也会自动归一
HARNESS_MODEL=glm-4.6
```

- 兼容旧命名 `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL`（`API_KEY` 优先）
- harness 节点走独立 HARNESS_* 三件套（Anthropic 协议），Claude Code SDK 子进程的
  `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / 模型均由它显式注入
  （`setting_sources=[]`，覆盖本机继承的 `ANTHROPIC_*`）；任一缺失，harness 节点启动即报错
- 模型选型提示：免费/flash 档模型在大结构化输出上偶发字段遗漏或指令泄漏，
  代码已内置防护（必填校验重试、标题清洗、少章重试、瞬态网络指数退避重试），
  但**质量要求高的场景建议用更强模型**（如 deepseek-chat 级别）

### 2. 逐阶段执行与验收点

```bash
export PYTHONIOENCODING=utf-8     # Windows GBK 控制台显示中文（可选）

poetry run biaoshu init --tender data/tender/服务招标文件.docx --kb data/company
```

| 阶段 | 命令 | 验收点（data/runs/<run_id>/ 下） |
|---|---|---|
| 解析 | `biaoshu parse` | `01_parse/`：metadata/requirements/scoring/invalidation 四 yaml 非空、`routing.yaml` 为关键词路由结果（含 `structure_mode`，无标题样式文档自动 LLM 重建结构）、`tender.md` 全文 |
| 模板 | `biaoshu template` | `02_template/template.md` 响应文件目录树 + report.md |
| 事实 | `biaoshu facts` | `03_facts.yaml`（工期/人员/指标/承诺）——**人工控制点**，可编辑 |
| 目录 | `biaoshu outline` | `04_outline.yaml`：三级提纲（一级章名对齐技术评分项、三级小节带 target_words）——**人工控制点**，可编辑 |
| 正文 | `biaoshu body` | `05_body/`：每个三级小节一个 `{id}-{标题}.md` + `body.md`（树状拼装）+ `body_review_round_N.md`（含"待修复小节"清单，回环只重写问题小节） |
| 填表 | `biaoshu fill` | `06_fill/forms|deviation/` 两个 docx（forms=其余填写部分整体：程序化 plan 填写 + harness 兜底；deviation=偏离表直出数据行） |
| 拼装 | `biaoshu assemble` | `07_draft/标书草稿_v1.docx` + latest.txt |
| 审核 | `biaoshu review` | `08_review/review_round_1.md`（五项检查 + `VERDICT: PASS|FAIL` 行） |
| 修改 | `biaoshu revise` | FAIL 时按意见修订出 `标书草稿_v2.docx` 并复审（≤2 轮，用尽仍 FAIL 则报告标注"需人工处理"） |

说明：

- **断点续跑**：任一阶段失败（网络/限流）后重跑同一命令即可从 checkpoint 恢复；
  阶段产物落盘后不会重复执行
- **人工编辑生效**：`03_facts.yaml` / `04_outline.yaml` 编辑后直接跑下一阶段，
  下游节点以文件为准（不需要重跑上一阶段）
- 一条命令全流程：`poetry run biaoshu run`
- 免费档模型偶发 429 上游限流：LLM 调用已内置指数退避重试（连接/超时/限流），
  连续失败时稍后重跑同一阶段命令即可

## 单元测试

```bash
poetry run pytest        # 无 LLM 成本（假模型 + mock harness）
```

## 配置项（.env 可选覆盖）

| 变量 | 默认 | 说明 |
|---|---|---|
| `API_KEY` / `MODEL_NAME` / `BASE_URL` | — | LLM 三件套（必填） |
| `HARNESS_API_KEY` / `HARNESS_BASE_URL` / `HARNESS_MODEL` | — | harness 三件套（必填，Anthropic 协议端点），不回退 LLM 三件套 |
| `BODY_CONCURRENCY` | 6 | 正文按三级小节并发生成的并发数 |
| `BODY_REVIEW_MAX_ROUNDS` | 2 | 正文审核回环上限 |
| `REVISE_MAX_ROUNDS` | 1 | 审核→修改回环上限（只修一轮；数据缺失类不计入 FAIL，归入报告「待人工补充」节） |
| `WORD_TOLERANCE` | 0.5 | 小节字数容差（±50%） |
| `KB_TOP_K` | 5 | 知识库检索片段数 |
| `HARNESS_MAX_TURNS` | 100 | harness 节点（Claude SDK）最大轮次 |
