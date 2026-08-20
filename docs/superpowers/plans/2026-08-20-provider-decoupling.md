# Provider 解耦(harness 独立三件套)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** harness 节点(claude CLI,Anthropic 协议)改用独立 `HARNESS_API_KEY` / `HARNESS_BASE_URL` / `HARNESS_MODEL` 三件套,删除从 LLM 三件套(OpenAI 协议)派生的 OpenRouter 耦合逻辑。

**Architecture:** 配置层(`config.py`)两套三件套并列、各自协议独立;`harness.py` 在唯一入口 `run_harness_task` 顶部校验三件套并显式注入子进程 env;`models.py`(LLM 侧 OpenAI 协议)逻辑不动。spec 见 `docs/superpowers/specs/2026-08-20-provider-decoupling-design.md`。

**Tech Stack:** Python 3.11+ · poetry · pydantic-settings · claude-agent-sdk · pytest

## Global Constraints

- 不新增依赖;LLM 侧固定 OpenAI 协议,不做协议选择器(spec §7)。
- 注释/docstring 用中文,风格与现有代码一致(简洁、讲"为什么")。
- 测试命令一律 `poetry run pytest`(Windows Git Bash 环境)。
- `HARNESS_MODEL` 旧 alias `HARNESS_MODEL_NAME` 保留兼容;`HARNESS_*` 不回退 LLM 三件套(spec §2)。
- 现有 LLM 侧测试全部保留不改语义(spec §5)。

---

### Task 1: config 增加 harness 三件套,删除派生逻辑

**Files:**
- Modify: `src/biaoshu_gen/config.py:28-51`(harness_model 字段区 + anthropic_base_url property + 过时注释)
- Test: `tests/test_config.py`(文件末尾追加)

**Interfaces:**
- Consumes: 无(首任务)
- Produces: `Settings.harness_api_key: str`、`Settings.harness_base_url: str`(validator 自动去尾 `/v1/messages`、`/v1`)、`Settings.harness_model: str`(alias `HARNESS_MODEL` / `HARNESS_MODEL_NAME`,不再有回退语义);**删除** `Settings.anthropic_base_url` property——Task 2 依赖这三个字段,不得再用 `anthropic_base_url`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 末尾追加:

```python
def test_settings_reads_harness_env(monkeypatch):
    monkeypatch.setenv("HARNESS_API_KEY", "sk-harness")
    monkeypatch.setenv("HARNESS_BASE_URL", "https://open.bigmodel.cn/api/anthropic")
    monkeypatch.setenv("HARNESS_MODEL", "glm-4.6")
    s = Settings(_env_file=None)
    assert s.harness_api_key == "sk-harness"
    assert s.harness_base_url == "https://open.bigmodel.cn/api/anthropic"
    assert s.harness_model == "glm-4.6"


def test_harness_defaults_empty():
    s = Settings(_env_file=None)
    assert s.harness_api_key == ""
    assert s.harness_base_url == ""
    assert s.harness_model == ""


def test_harness_base_url_normalizes_trailing_paths():
    """带 /v1/messages 或 /v1 尾巴都归一为 Anthropic base(CLI 自拼 /v1/messages)。"""
    s1 = Settings(_env_file=None, harness_base_url="https://openrouter.ai/api/v1/messages")
    assert s1.harness_base_url == "https://openrouter.ai/api"
    s2 = Settings(_env_file=None, harness_base_url="https://openrouter.ai/api/v1")
    assert s2.harness_base_url == "https://openrouter.ai/api"
    s3 = Settings(_env_file=None, harness_base_url="https://api.anthropic.com")
    assert s3.harness_base_url == "https://api.anthropic.com"
    s4 = Settings(_env_file=None, harness_base_url="")
    assert s4.harness_base_url == ""


def test_anthropic_base_url_property_removed():
    """派生逻辑(OpenRouter 双协议耦合)已删,不得再出现。"""
    assert not hasattr(Settings(_env_file=None), "anthropic_base_url")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `poetry run pytest tests/test_config.py -v`
Expected: FAIL——`test_settings_reads_harness_env` 等报 `AttributeError: ... 'Settings' object has no attribute 'harness_api_key'`;`test_anthropic_base_url_property_removed` FAIL(property 仍在)。

- [ ] **Step 3: 最小实现**

`src/biaoshu_gen/config.py`——把现有 `harness_model` 字段(28-33 行)、`anthropic_base_url` property(44-49 行)和 51 行过时注释整体替换。删除:

```python
    # harness 节点（claude CLI）可用独立模型；缺省跟随 llm_model。
    # 用途：当主模型额度紧张时，可把 HARNESS_MODEL 指向免费档模型，避免 402。
    harness_model: str = Field(
        default="",
        validation_alias=AliasChoices("HARNESS_MODEL", "HARNESS_MODEL_NAME"),
    )
```

```python
    @property
    def anthropic_base_url(self) -> str:
        """claude CLI（Anthropic 协议）用的 base：CLI 自动追加 /v1/messages，
        OpenAI 风格 base（…/v1）需去尾 /v1（如 OpenRouter 的 …/api/v1/messages）。"""
        b = self.llm_base_url.rstrip("/")
        return b[: -len("/v1")] if b.endswith("/v1") else b

    # harness 节点走 claude-agent-sdk，继承本机 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN，无需配置
```

在原 `harness_model` 位置写入:

```python
    # harness 三件套（Anthropic 协议端点，claude CLI 子进程用）。
    # 与 LLM 三件套相互独立、不回退：双协议网关（OpenRouter）只是恰好可两端同配。
    harness_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("HARNESS_API_KEY"),
    )
    harness_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("HARNESS_BASE_URL"),
    )
    # harness 模型不回退 llm_model：独立 provider 的模型命名空间不同，回退必然错。
    harness_model: str = Field(
        default="",
        validation_alias=AliasChoices("HARNESS_MODEL", "HARNESS_MODEL_NAME"),
    )
```

在 `_strip_completions_path` validator 之后追加:

```python
    @field_validator("harness_base_url")
    @classmethod
    def _strip_messages_path(cls, v: str) -> str:
        """归一写完整端点（…/v1/messages）或带 /v1 尾巴的情况：
        claude CLI（Anthropic SDK）自拼 /v1/messages，base 不能带。空串跳过。"""
        if not v:
            return v
        for suffix in ("/v1/messages", "/v1"):
            if v.endswith(suffix):
                return v[: -len(suffix)]
        return v
```

- [ ] **Step 4: 跑测试确认通过**

Run: `poetry run pytest tests/test_config.py -v`
Expected: PASS(含原有 LLM 侧测试全部不变绿)。

- [ ] **Step 5: 提交**

```bash
git add src/biaoshu_gen/config.py tests/test_config.py
git commit -m "feat: config 增加 HARNESS_* 三件套（Anthropic 协议），删除 openrouter 派生逻辑"
```

---

### Task 2: harness 校验三件套并显式注入

**Files:**
- Modify: `src/biaoshu_gen/harness.py:1-5`(模块 docstring)、`src/biaoshu_gen/harness.py:54-92`(`_query_sdk`)、`src/biaoshu_gen/harness.py:161-187`(`run_harness_task`)
- Test: `tests/test_harness.py`(新增 fixture + 2 个新测试;4 个既有测试加 fixture 参数)

**Interfaces:**
- Consumes: Task 1 的 `Settings.harness_api_key` / `harness_base_url` / `harness_model`。
- Produces: `run_harness_task` 契约变更——三件套任一为空时,在任何 SDK 调用之前抛 `HarnessError`(消息列出缺失变量名);子进程 env 注入 `ANTHROPIC_BASE_URL=harness_base_url`、`ANTHROPIC_AUTH_TOKEN=harness_api_key`、模型族=`harness_model`。

- [ ] **Step 1: 写失败测试**

`tests/test_harness.py`——先在 import 区之后加 fixture:

```python
@pytest.fixture
def harness_settings(monkeypatch):
    """注入合法 harness 三件套（run_harness_task 入口校验需要），不依赖本机 .env。"""
    from biaoshu_gen.config import Settings
    fake = Settings(
        _env_file=None,
        harness_api_key="sk-test-harness",
        harness_base_url="https://gw.example.com/anthropic",
        harness_model="test-model",
    )
    monkeypatch.setattr(harness, "get_settings", lambda: fake)
```

再在文件末尾追加三个测试:

```python
def test_run_harness_task_requires_harness_settings(tmp_path: Path, monkeypatch):
    """三件套缺失 -> 立即抛 HarnessError，不触发 SDK 调用（重试循环之前）。"""
    from biaoshu_gen.config import Settings
    monkeypatch.setattr(harness, "get_settings",
                        lambda: Settings(_env_file=None))          # 三件套全空

    async def must_not_run(prompt, cwd, max_turns):
        raise AssertionError("SDK 不应被调用")

    monkeypatch.setattr(harness, "_query_sdk", must_not_run)
    task = HarnessTask(prompt="p", cwd=tmp_path, expected_outputs=[tmp_path / "expected.md"])
    with pytest.raises(HarnessError) as e:
        run_harness_task(task)
    assert "HARNESS_API_KEY" in str(e.value)
    assert "HARNESS_BASE_URL" in str(e.value)
    assert "HARNESS_MODEL" in str(e.value)


def test_run_harness_task_error_names_only_missing_vars(tmp_path: Path, monkeypatch):
    from biaoshu_gen.config import Settings
    monkeypatch.setattr(harness, "get_settings",
                        lambda: Settings(_env_file=None, harness_api_key="sk-x"))

    async def must_not_run(prompt, cwd, max_turns):
        raise AssertionError("SDK 不应被调用")

    monkeypatch.setattr(harness, "_query_sdk", must_not_run)
    task = HarnessTask(prompt="p", cwd=tmp_path, expected_outputs=[tmp_path / "expected.md"])
    with pytest.raises(HarnessError) as e:
        run_harness_task(task)
    assert "HARNESS_API_KEY" not in str(e.value)      # 已配置的不点名
    assert "HARNESS_BASE_URL" in str(e.value)


def test_query_sdk_injects_harness_env(harness_settings, tmp_path: Path, monkeypatch):
    """env 注入来自 harness 三件套：不派生、不复用 llm key、不回退 llm 模型。"""
    import claude_agent_sdk as cas
    captured = {}

    async def fake_query(*, prompt, options):
        captured["env"] = dict(options.env)
        captured["model"] = options.model
        return
        yield                                  # 使其成为 async generator

    monkeypatch.setattr(cas, "query", fake_query)
    import asyncio
    asyncio.run(harness._query_sdk("提示", tmp_path, 3))
    assert captured["model"] == "test-model"
    assert captured["env"]["ANTHROPIC_BASE_URL"] == "https://gw.example.com/anthropic"
    assert captured["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-test-harness"
    assert captured["env"]["ANTHROPIC_MODEL"] == "test-model"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `poetry run pytest tests/test_harness.py -v`
Expected: FAIL——`test_run_harness_task_requires_harness_settings` / `test_run_harness_task_error_names_only_missing_vars`:当前无校验,task 直入 SDK 调用,`must_not_run` 抛的 AssertionError 被重试循环捕获、3 次后原样抛出,不是 `HarnessError` 且消息不含变量名;`test_query_sdk_injects_harness_env`:Task 1 已删 `anthropic_base_url`,`_query_sdk` 取它时 AttributeError。同时 4 个既有 `test_run_harness_task_*` 仍 PASS(尚未加校验)。

- [ ] **Step 3: 最小实现**

`src/biaoshu_gen/harness.py` 三处修改。

① 模块 docstring(1-5 行)改为:

```python
"""Claude Code SDK（claude-agent-sdk）封装：文件操作型 harness 节点统一入口。

SDK 以子进程方式拉起 claude CLI，Anthropic 协议端点由 .env 的 HARNESS_* 三件套
显式注入（setting_sources=[]，覆盖本机继承的 ANTHROPIC_* 环境变量）。
"""
```

② `_query_sdk`(54-92 行)——`s = get_settings()` 之后的模型行与 env 字典改为:

```python
    s = get_settings()
    # harness 模型独立配置（HARNESS_MODEL），不回退 llm_model（命名空间不同）。
    model = s.harness_model
```

```python
        # 全面使用 .env 的 HARNESS_* 三件套（Anthropic 协议端点），
        # 覆盖本机继承的 ANTHROPIC_* 环境变量。
        env={
            "ANTHROPIC_BASE_URL": s.harness_base_url,
            "ANTHROPIC_AUTH_TOKEN": s.harness_api_key,
            "ANTHROPIC_MODEL": model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        },
```

③ `run_harness_task`(161-163 行)——新增校验辅助函数(放在 `run_harness_task` 定义之前)并改造开头:

```python
def _require_harness_settings(s) -> None:
    """harness 三件套（Anthropic 协议端点）缺失即抛错——独立 provider，不回退 LLM 三件套。"""
    missing = [name for name, val in (
        ("HARNESS_API_KEY", s.harness_api_key),
        ("HARNESS_BASE_URL", s.harness_base_url),
        ("HARNESS_MODEL", s.harness_model),
    ) if not val]
    if missing:
        raise HarnessError(
            "harness 节点缺少配置（Anthropic 协议端点，请在 .env 配置）："
            + " / ".join(missing)
        )
```

```python
def run_harness_task(task: HarnessTask) -> list[Path]:
    """执行任务；先校验三件套；SDK 异常重试（≤3 次退避）；产物缺失再带反馈重试一次 -> 仍失败抛 HarnessError。"""
    s = get_settings()
    _require_harness_settings(s)
    max_turns = task.max_turns or s.harness_max_turns
```

(原 `max_turns = task.max_turns or get_settings().harness_max_turns` 一行删去,`s` 复用。)

- [ ] **Step 4: 更新既有测试并全部跑绿**

既有 4 个测试加 `harness_settings` fixture 参数(签名各加一个参数,函数体不动):

- `test_run_harness_task_success(tmp_path: Path, harness_settings, monkeypatch)`
- `test_run_harness_task_retries_once_then_raises(tmp_path: Path, harness_settings, monkeypatch)`
- `test_run_harness_task_retry_can_succeed(tmp_path: Path, harness_settings, monkeypatch)`
- `test_run_harness_task_retries_on_sdk_exception(tmp_path: Path, harness_settings, monkeypatch)`

Run: `poetry run pytest tests/test_harness.py -v`
Expected: PASS(全部 9 个:4 个既有 + fixture 后无一受校验牵连,3 个新测试,`test_find_run_dir`/workspace/environment_notes 不涉配置)。

- [ ] **Step 5: 全量回归**

Run: `poetry run pytest`
Expected: PASS(假模型 + mock harness,无 LLM 成本)。已核实其余测试不受影响:`test_node_fill.py` 与 `test_node_extract_template.py` 在调用点 mock `run_harness_task` 本身,校验不触发;`test_node_review.py`/`test_node_revise.py`/`test_cli.py`/`test_integration.py` 不触达 harness 配置。若仍有测试经真实 `run_harness_task`,给该测试加 `harness_settings` fixture(fixture 定义在 `tests/test_harness.py`,跨文件需要时移入 `tests/conftest.py`)。

- [ ] **Step 6: 提交**

```bash
git add src/biaoshu_gen/harness.py tests/test_harness.py
git commit -m "feat: harness 校验并注入独立 HARNESS_* 三件套，不再回退 LLM 配置"
```

---

### Task 3: 配置样例与文档对齐

**Files:**
- Modify: `.env.example`(全文重写)
- Modify: `README.md:8-16`(技术栈/安装)、`README.md:51-65`(配置节)、`README.md:108`(配置表)
- Modify: `src/biaoshu_gen/models.py:1`(模块 docstring)

**Interfaces:**
- Consumes: Task 1/2 的变量名与语义(`HARNESS_API_KEY` / `HARNESS_BASE_URL` / `HARNESS_MODEL`,必填不回退,base 自动归一)。
- Produces: 无代码接口;交付对齐后的 `.env.example`/README。

- [ ] **Step 1: 重写 `.env.example`**

```ini
# LLM 三件套（必填，OpenAI 协议端点：OpenRouter / DeepSeek 官方等）
API_KEY=sk-你的key
MODEL_NAME=deepseek/deepseek-v4-flash-0731
BASE_URL=https://openrouter.ai/api/v1
# BASE_URL 写完整 …/v1/chat/completions 也可以，代码会自动归一
# 兼容旧命名 DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_BASE_URL（上面的通用命名优先）

# harness 三件套（必填，Anthropic 协议端点：智谱 / Anthropic 官方 / OpenRouter 等）
# 与 LLM 三件套相互独立、不回退；harness 节点（claude CLI）启动时校验，缺失即报错
HARNESS_API_KEY=sk-你的harness-key
HARNESS_BASE_URL=https://open.bigmodel.cn/api/anthropic
# HARNESS_BASE_URL 写成 …/v1 或 …/v1/messages 也可以，代码会自动归一（claude CLI 自拼 /v1/messages）
HARNESS_MODEL=glm-4.6

# 流程控制参数（均可选，注释值即默认值）
# BODY_CONCURRENCY=6        # 正文按三级小节并发生成的并发数
# BODY_REVIEW_MAX_ROUNDS=2  # 正文审核回环上限
# REVISE_MAX_ROUNDS=2       # 审核→修改回环上限
# WORD_TOLERANCE=0.5        # 小节字数容差（±50%）
# KB_TOP_K=5                # 知识库检索片段数
# HARNESS_MAX_TURNS=100     # harness 节点（Claude SDK）最大轮次
```

- [ ] **Step 2: 改 `README.md` 四处**

① 技术栈(9-10 行):

```markdown
Python 3.11+ · poetry · LangGraph（单一状态图 + SqliteSaver 断点续跑）·
PydanticAI（结构化输出节点，OpenAI 协议端点：OpenRouter / DeepSeek 等）·
Claude Code SDK（harness 文件操作节点，独立 HARNESS_* 三件套注入 Anthropic 协议端点）
```

② 安装(16 行):

```markdown
cp .env.example .env   # 写入两套三件套：API_KEY/MODEL_NAME/BASE_URL（OpenAI 协议）
                        # + HARNESS_API_KEY/HARNESS_BASE_URL/HARNESS_MODEL（Anthropic 协议）
```

③ 「### 1. 配置 `.env`」节(51-65 行)——标题改为「### 1. 配置 `.env`（两套三件套，各自协议独立）」,ini 块后追加:

```ini
HARNESS_API_KEY=sk-你的harness-key    # Anthropic 协议端点 key（智谱 / Anthropic 官方 / OpenRouter 等）
HARNESS_BASE_URL=https://open.bigmodel.cn/api/anthropic   # 写 …/v1 或 …/v1/messages 也会自动归一
HARNESS_MODEL=glm-4.6
```

并把 60-62 行的派生 bullet 替换为:

```markdown
- harness 节点走独立 HARNESS_* 三件套（Anthropic 协议），Claude Code SDK 子进程的
  `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / 模型均由它显式注入
  （`setting_sources=[]`，覆盖本机继承的 `ANTHROPIC_*`）；任一缺失，harness 节点启动即报错
```

④ 配置表(107-108 行)——`HARNESS_MODEL` 行替换为:

```markdown
| `HARNESS_API_KEY` / `HARNESS_BASE_URL` / `HARNESS_MODEL` | — | harness 三件套（必填，Anthropic 协议端点），不回退 LLM 三件套 |
```

- [ ] **Step 3: 改 `models.py:1` 模块 docstring**

```python
"""PydanticAI Agent 工厂：任意 OpenAI 兼容端点（配置见 config，协议与 harness 三件套独立）。"""
```

- [ ] **Step 4: 残留检查 + 全量回归**

Run: `grep -rn "anthropic_base_url\|跟随 llm_model\|跟随 \`MODEL_NAME\`\|派生注入" src README.md .env.example`
Expected: 无输出(派生/回退表述清零)。

Run: `poetry run pytest`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add .env.example README.md src/biaoshu_gen/models.py
git commit -m "docs: .env.example/README 对齐 harness 独立三件套（Anthropic 协议）"
```

---

## 验收清单(对照 spec §6)

- [ ] LLM-only 子命令(parse/outline/body 等)与全量单测在缺 HARNESS_* 时不受影响
- [ ] 缺任一 HARNESS_* 时 harness 节点启动即报错,错误信息含缺失变量名
- [ ] `HARNESS_BASE_URL` 写裸 base / `…/v1` / `…/v1/messages` 三种形态均可用
- [ ] OpenRouter 作 harness 端点仍可用(`HARNESS_BASE_URL=https://openrouter.ai/api`)
