# Provider 解耦设计:harness 独立三件套

- 日期:2026-08-20
- 状态:已与需求方逐节确认
- 上游依据:用户需求「模型 provider 不绑定 OpenRouter;harness provider 与 LLM provider 分开设置,一个 OpenAI 协议、一个 Anthropic 协议」

## 1. 背景与问题

当前两条模型链路:

| 环节 | 协议 | 配置来源 |
|---|---|---|
| LLM 节点(`models.py`,PydanticAI) | OpenAI | `API_KEY` / `MODEL_NAME` / `BASE_URL`(任意 OpenAI 兼容端点) |
| harness 节点(`harness.py`,claude CLI 子进程) | Anthropic | **派生**:`ANTHROPIC_BASE_URL` 由 `llm_base_url` 去尾 `/v1` 算出,`ANTHROPIC_AUTH_TOKEN` 复用 `llm_api_key`,仅 `HARNESS_MODEL` 可独立(缺省仍回退 `llm_model`) |

派生逻辑(`config.py` 的 `anthropic_base_url` property)假设「同一服务商同时提供 OpenAI 与 Anthropic 两种协议」——只有 OpenRouter 这类双协议网关成立。换成「DeepSeek 官方(OpenAI 协议)+ 智谱 Anthropic 网关」这类组合即断,且报错发生在 claude CLI 子进程深处,难排查。

## 2. 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 回退策略 | **必须显式配置**,不回退到 LLM 三件套;缺失即报清晰错误 |
| 命名 | `HARNESS_API_KEY` / `HARNESS_BASE_URL` / `HARNESS_MODEL`(与现有 `HARNESS_MODEL` 连续,不与本机 `ANTHROPIC_*` 环境变量混淆) |
| 协议分工 | LLM 侧固定 OpenAI 协议;harness 侧固定 Anthropic 协议;不做协议选择器 |
| 校验时机 | Settings 构造不强制(空串为合法 default);`run_harness_task` 入口校验,缺失立即抛错 |
| `HARNESS_MODEL` 回退 | 删除「缺省跟随 `llm_model`」——独立 provider 的模型命名空间不同,回退必然错 |

## 3. 配置面(`config.py`)

两套三件套并列,各自协议独立:

| .env 变量 | 字段 | 协议 | 消费者 |
|---|---|---|---|
| `API_KEY` / `MODEL_NAME` / `BASE_URL` | `llm_api_key` / `llm_model` / `llm_base_url`(不变) | OpenAI | `models.py` PydanticAI 节点 |
| `HARNESS_API_KEY` / `HARNESS_BASE_URL` / `HARNESS_MODEL` | `harness_api_key` / `harness_base_url` / `harness_model` | Anthropic | `harness.py` claude CLI 子进程 |

改动点:

- **删除** `anthropic_base_url` property 及 `/v1` 派生逻辑(耦合根源)。
- 新增字段 `harness_api_key`、`harness_base_url`,default 空串,alias 分别为 `HARNESS_API_KEY`、`HARNESS_BASE_URL`;`harness_model` 保留现有字段与 alias,仅删除回退语义(注释同步)。
- 新增 `harness_base_url` validator:依次去尾 `/v1/messages`、`/v1`(Anthropic SDK 自拼 `/v1/messages`),镜像 LLM 侧 `_strip_completions_path` 的归一风格;空串跳过归一。
- `harness_model` 的旧 alias `HARNESS_MODEL_NAME` 保留兼容。
- 同步更新字段注释:删除「harness 节点继承本机 `ANTHROPIC_*`,无需配置」的过时说明(config.py 现存注释与实际行为早已不符)。

## 4. 校验与注入(`harness.py`)

- `run_harness_task` 入口新增校验:三件套任一为空即抛 `HarnessError`,信息列出缺失变量名并注明「Anthropic 协议端点」。校验在 SDK 重试循环之前,不浪费重试。
- `_query_sdk` 的 env 注入改为:

```python
env={
    "ANTHROPIC_BASE_URL": s.harness_base_url,   # 不再派生
    "ANTHROPIC_AUTH_TOKEN": s.harness_api_key,  # 不再复用 llm key
    "ANTHROPIC_MODEL": s.harness_model,         # 不再回退 llm_model
    # ANTHROPIC_DEFAULT_OPUS/SONNET/HAIKU_MODEL 三个映射、setting_sources=[] 保持不变
}
```

`models.py` 逻辑不动,仅把模块 docstring 中「OpenRouter」字样改为「任意 OpenAI 兼容端点」。

## 5. 文档与测试

- `.env.example`:两套三件套分块注释,各标明协议;删除旧 `HARNESS_MODEL` 单独注释块(并入 harness 三件套);示例值给 OpenRouter(OpenAI 协议)+ 智谱/Anthropic(Anthropic 协议)各一行说明。
- README:架构行、接入模型一节、配置表同步为两套三件套;删除「harness 节点不需要单独配置(派生注入)」表述。
- `tests/test_config.py`:
  - 新增:harness alias 读取;`harness_base_url` 归一(带 `/v1/messages`、带 `/v1`、裸 base、空串);三件套缺失时 `run_harness_task` 快速抛 `HarnessError`(monkeypatch SDK 断言未触发)。
  - 保留:现有 LLM 侧全部测试(alias 优先级、completions 路径归一等)。

## 6. 兼容性

- 现网 `.env` 必须补 `HARNESS_API_KEY` / `HARNESS_BASE_URL` / `HARNESS_MODEL` 三项,否则 harness 节点启动即报错(错误信息可操作)。这是需求方已接受的显式选择。
- OpenRouter 仍可作为 harness 端点(`HARNESS_BASE_URL=https://openrouter.ai/api`),只是不再隐式。
- LLM-only 流程(parse/outline/body 等非 harness 子命令)与单元测试不受缺失 harness 配置影响。

## 7. 明确不做(YAGNI)

- LLM 侧协议选择器(固定 OpenAI 协议)。
- provider 注册表 / 多 profile 抽象层。
- 本机 `ANTHROPIC_*` 环境变量继承(继续 `setting_sources=[]` + 显式注入,行为不变)。
