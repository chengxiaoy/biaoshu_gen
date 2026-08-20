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
poetry run biaoshu init --tender data/tender/软件招标文件.docx --kb data/company
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

poetry run biaoshu init --tender data/tender/软件招标文件.docx --kb data/company
```

| 阶段 | 命令 | 验收点（data/runs/<run_id>/ 下） |
|---|---|---|
| 解析 | `biaoshu parse` | `01_parse/`：metadata/requirements/scoring/invalidation 四 yaml 非空、`routing.yaml` 为关键词路由结果、`tender.md` 全文 |
| 模板 | `biaoshu template` | `02_template/template.md` 响应文件目录树 + report.md |
| 事实 | `biaoshu facts` | `03_facts.yaml`（工期/人员/指标/承诺）——**人工控制点**，可编辑 |
| 目录 | `biaoshu outline` | `04_outline.yaml`：三级提纲（一级章名对齐技术评分项、三级小节带 target_words）——**人工控制点**，可编辑 |
| 正文 | `biaoshu body` | `05_body/`：每个三级小节一个 `{id}-{标题}.md` + `body.md`（树状拼装）+ `body_review_round_N.md`（含"待修复小节"清单，回环只重写问题小节） |
| 填表 | `biaoshu fill` | `06_fill/forms|deviation|commercial/` 三个 docx（真实调用 Claude Code SDK 填写） |
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
| `REVISE_MAX_ROUNDS` | 2 | 审核→修改回环上限 |
| `WORD_TOLERANCE` | 0.5 | 小节字数容差（±50%） |
| `KB_TOP_K` | 5 | 知识库检索片段数 |
| `HARNESS_MAX_TURNS` | 100 | harness 节点（Claude SDK）最大轮次 |
