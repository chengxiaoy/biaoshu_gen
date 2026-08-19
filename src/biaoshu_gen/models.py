"""PydanticAI Agent 工厂：OpenAI 兼容端点（OpenRouter / DeepSeek 等，配置见 config）。"""
import httpx
import time

from openai import APIConnectionError, APITimeoutError, RateLimitError
from pydantic import BaseModel

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .config import get_settings

_REQUEST_TIMEOUT_S = 600.0   # 长 prompt + 慢模型（免费档）需要充裕超时
# pydantic-ai 会把 openai 的连接/超时/限流错误包装成 ModelAPIError 抛出，故须一并捕获
_TRANSIENT_ERRORS = (ModelAPIError, APIConnectionError, APITimeoutError, RateLimitError)
_TRANSIENT_RETRIES = 4


def make_agent(output_type: type[BaseModel], system_prompt: str, retries: int = 2) -> Agent:
    """创建指向配置端点的 PydanticAI Agent（所有非 harness LLM 节点的统一入口）。

    pydantic-ai 1.107.5 的 OpenAIChatModel 不接受 api_key/base_url 关键字，
    改经 OpenAIProvider 传入；对外工厂接口不变。
    """
    s = get_settings()
    provider = OpenAIProvider(
        base_url=s.llm_base_url,
        api_key=s.llm_api_key or None,  # 空串归一为 None，让 provider 回退占位符 key
        http_client=httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S),
    )
    model = OpenAIChatModel(s.llm_model, provider=provider)
    return Agent(model=model, output_type=output_type, system_prompt=system_prompt, retries=retries)


def run_sync(agent: Agent, prompt: str):
    """执行 agent.run_sync，对瞬态网络错误（连接/超时/限流）指数退避重试。

    OpenRouter 免费档上游限流与跨境网络抖动常见，节点统一经本函数调用。
    """
    delay = 10.0
    for attempt in range(_TRANSIENT_RETRIES):
        try:
            return agent.run_sync(prompt)
        except _TRANSIENT_ERRORS:
            if attempt == _TRANSIENT_RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")
