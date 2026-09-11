"""全局配置：经 .env / 环境变量注入，POC 阶段路径均相对仓库根。"""
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# LLM_REASONING_EFFORT 合法值（validator 与 models.llm_model_settings 共用,单一来源）
REASONING_EFFORTS = frozenset(("minimal", "low", "medium", "high"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True,
    )

    # PydanticAI 非 harness 节点的 LLM（OpenAI 兼容端点，如 OpenRouter / DeepSeek）。
    # 优先读 .env 通用三件套 API_KEY/MODEL_NAME/BASE_URL；兼容 DEEPSEEK_* 旧命名。
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("API_KEY", "DEEPSEEK_API_KEY", "DEEPSEEK_APIKEY"),
    )
    llm_model: str = Field(
        default="deepseek-chat",
        validation_alias=AliasChoices("MODEL_NAME", "DEEPSEEK_MODEL"),
    )
    llm_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices("BASE_URL", "DEEPSEEK_BASE_URL"),
    )
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
    # harness 思考力度（claude-agent-sdk 的 effort 档）：合法 low/medium/high/xhigh/max，
    # 归空 = 不传、跟随 CLI 默认。默认 high——flash 档模型在 fill 插图任务上曾 9~13 轮
    # 即中途收回合（#89 端到端取证），higher effort 引导先想清再动手。
    harness_effort: str = Field(
        default="high",
        validation_alias=AliasChoices("HARNESS_EFFORT"),
    )

    @field_validator("harness_effort")
    @classmethod
    def _normalize_harness_effort(cls, v: str) -> str:
        """只认 SDK EffortLevel 的值（大小写不敏感），其余归空 = 不传。"""
        v = v.strip().lower()
        return v if v in ("low", "medium", "high", "xhigh", "max") else ""

    # DeepSeek V4 思考模式开关（经 extra_body 注入 thinking 字段）：
    # V4 思考模式默认开启且拒绝强制 tool_choice，结构化输出（ToolOutput）在其官方端点必 400，
    # 官方直连需设 disabled；OpenRouter 网关自会兼容，留空即不注入、跟随 provider 默认。
    llm_thinking: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_THINKING"),
    )

    @field_validator("llm_thinking")
    @classmethod
    def _normalize_thinking(cls, v: str) -> str:
        """只认 enabled/disabled（大小写不敏感），其余归空 = 跟随 provider 默认。"""
        v = v.strip().lower()
        return v if v in ("enabled", "disabled") else ""

    # 推理力度（pydantic-ai 原生 openai_reasoning_effort 直达请求体）：o 系/GPT-5 及
    # 兼容网关语义 minimal/low/medium/high；留空跟随 provider 默认；未知值归空。
    llm_reasoning_effort: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_REASONING_EFFORT", "REASONING_EFFORT"),
    )

    @field_validator("llm_reasoning_effort")
    @classmethod
    def _normalize_reasoning_effort(cls, v: str) -> str:
        """只认 REASONING_EFFORTS 中的值（大小写不敏感），其余归空 = 跟随 provider 默认。"""
        v = v.strip().lower()
        return v if v in REASONING_EFFORTS else ""

    @field_validator("llm_base_url")
    @classmethod
    def _strip_completions_path(cls, v: str) -> str:
        """兼容 .env 里写完整端点（…/v1/chat/completions）的情况：OpenAI SDK 只接受 base_url。"""
        for suffix in ("/chat/completions", "/completions"):
            if v.endswith(suffix):
                return v[: -len(suffix)]
        return v

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

    # RAGFlow（kb_v2 知识库 v2）：远程 server 连接与命名，.env 注入 RAGFLOW_*。
    # base_url 不带 /api/v1 尾巴（SDK 自拼）；默认端口 9380 为 RAGFlow 出厂值。
    ragflow_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("RAGFLOW_API_KEY"),
    )
    ragflow_base_url: str = Field(
        default="http://localhost:9380",
        validation_alias=AliasChoices("RAGFLOW_BASE_URL"),
    )
    # 产品知识库固定 dataset 名：本地开发阶段所有 run 共用一个库，init 幂等增量上传。
    ragflow_dataset_name: str = Field(
        default="biaoshu-products",
        validation_alias=AliasChoices("RAGFLOW_DATASET_NAME"),
    )
    ragflow_chat_name: str = "biaoshu-assistant"    # Agentic RAG 问答助手名，get-or-create
    ragflow_llm_id: str = ""                        # 助手 LLM id；空用租户默认（见 tests/test_ragflow.py 的 model）

    data_dir: Path = Path("data")

    # 流程控制参数（设计文档 §7）
    body_review_max_rounds: int = 1
    revise_max_rounds: int = 1         # review→revise 只修一轮；数据缺口类已不计入 FAIL，多轮收益低
    word_tolerance: float = 1
    harness_max_turns: int = 20    # fill 插图 pass 等单任务通道,长上限只会烧 token 不收敛
    kb_top_k: int = 5
    body_concurrency: int = 6         # 正文按三级小节并发生成的并发数
    parse_concurrency: int = 6        # parse 分组抽取的并发数(#69)
    media_table_limit: int = 3        # rich_body：全书表格数量上限
    media_figure_limit: int = 3       # rich_body：全书 mermaid 图数量上限
    # mermaid 渲染校验（rich_body figure 的真实渲染检查）：依赖 mmdc（@mermaid-js/mermaid-cli）
    mermaid_render: bool = True            # False 时只用结构校验
    mermaid_cli: str = "mmdc"              # 可执行文件名或完整路径（which 解析）
    mermaid_render_timeout: float = 60.0   # 单次渲染超时（秒）
    mermaid_puppeteer_config: str = ""     # 留空自动探测 Edge/Chrome；可指向自定义 puppeteer json


@lru_cache
def get_settings() -> Settings:
    return Settings()


def runs_root() -> Path:
    """全部 run 目录的根——runs 布局的唯一定义点(cli/models/state 共用)。"""
    return get_settings().data_dir / "runs"
