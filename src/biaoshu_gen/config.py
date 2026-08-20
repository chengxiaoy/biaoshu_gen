"""全局配置：经 .env / 环境变量注入，POC 阶段路径均相对仓库根。"""
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    data_dir: Path = Path("data")

    # 流程控制参数（设计文档 §7）
    body_review_max_rounds: int = 2
    revise_max_rounds: int = 2
    word_tolerance: float = 0.5
    harness_max_turns: int = 100
    kb_top_k: int = 5
    body_concurrency: int = 6         # 正文按三级小节并发生成的并发数


@lru_cache
def get_settings() -> Settings:
    return Settings()
