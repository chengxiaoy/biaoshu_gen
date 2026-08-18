"""PydanticAI Agent 工厂：DeepSeek（OpenAI 兼容端点）。"""
from pydantic import BaseModel

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .config import get_settings


def make_agent(output_type: type[BaseModel], system_prompt: str, retries: int = 2) -> Agent:
    """创建指向 DeepSeek 的 PydanticAI Agent（所有非 harness LLM 节点的统一入口）。

    pydantic-ai 1.107.5 的 OpenAIChatModel 不接受 api_key/base_url 关键字，
    改经 OpenAIProvider 传入；对外工厂接口不变。
    """
    s = get_settings()
    provider = OpenAIProvider(
        base_url=s.deepseek_base_url,
        api_key=s.deepseek_api_key or None,  # 空串归一为 None，让 provider 回退占位符 key
    )
    model = OpenAIChatModel(s.deepseek_model, provider=provider)
    return Agent(model=model, output_type=output_type, system_prompt=system_prompt, retries=retries)
