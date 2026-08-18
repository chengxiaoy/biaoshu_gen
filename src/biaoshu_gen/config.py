"""全局配置：经 .env / 环境变量注入，POC 阶段路径均相对仓库根。"""
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True,
    )

    # DeepSeek（PydanticAI 非 harness 节点）。兼容 DEEPSEEK_API_KEY 与 DEEPSEEK_APIKEY 两种命名，
    # 前者优先（.env 里常写作 DEEPSEEK_APIKEY，避免 key 落空导致鉴权失败）。
    deepseek_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "DEEPSEEK_APIKEY"),
    )
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    # harness 节点走 claude-agent-sdk，继承本机 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN，无需配置

    data_dir: Path = Path("data")

    # 流程控制参数（设计文档 §7）
    body_review_max_rounds: int = 2
    revise_max_rounds: int = 2
    word_tolerance: float = 0.2
    harness_max_turns: int = 100
    kb_top_k: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
