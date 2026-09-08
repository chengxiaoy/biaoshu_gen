"""PydanticAI Agent 工厂：任意 OpenAI 兼容端点（配置见 config，协议与 harness 三件套独立）。"""
import logging
import os
import time

import httpx
from openai import APIConnectionError, APITimeoutError, RateLimitError
from pydantic import BaseModel

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from .config import get_settings, runs_root

log = logging.getLogger(__name__)

_REQUEST_TIMEOUT_S = 600.0   # 长 prompt + 慢模型（免费档）需要充裕超时
# pydantic-ai 会把 openai 的连接/超时/限流错误包装成 ModelAPIError 抛出，故须一并捕获
_TRANSIENT_ERRORS = (ModelAPIError, APIConnectionError, APITimeoutError, RateLimitError)
_TRANSIENT_RETRIES = 4
# UnexpectedModelBehavior=agent 内部重采样(retries)用尽仍校验不过——确定性错误,
# 指数退避无益(同 prompt 大概率同输出),短延迟快速重试即可(fill 大 prompt 节点最坏省 ~70s 白等)
_VALIDATION_RETRIES = 2
_VALIDATION_RETRY_DELAY_S = 2.0


def thinking_model_settings(llm_thinking: str) -> ModelSettings | None:
    """LLM_THINKING → 请求体注入（DeepSeek V4 思考模式默认开，且思考模式拒绝强制
    tool_choice——结构化输出 ToolOutput 在官方端点必 400，disabled 一刀解）。
    空串/未知值返回 None，不加 model_settings，跟随 provider 默认（OpenRouter 无感）。
    """
    if llm_thinking not in ("enabled", "disabled"):
        return None
    # OpenAI SDK 不认识 thinking 字段，须经 extra_body 透传（DeepSeek 官方文档约定）
    return ModelSettings(extra_body={"thinking": {"type": llm_thinking}})


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
    model = OpenAIChatModel(s.llm_model, provider=provider,
                            settings=thinking_model_settings(s.llm_thinking))
    return Agent(model=model, output_type=output_type, system_prompt=system_prompt, retries=retries)


def _dump_llm_io(label: str, kind: str, text: str) -> None:
    """LLM 全量输入/输出转储到 run/llm_debug/<label>_<seq>_<kind>.txt,日志可指向。

    glob 计数定序号是有意的:fill 各阶段是独立进程,进程内计数器会撞号。
    pytest 下必须静默跳过:单测经 FunctionModel 也会流经本函数,若不挡,
    合成夹具会按 .latest 灌进真实 run 的调试目录(2026-08-27 实测污染 75/143)。
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        root = runs_root()
        run = (root / ".latest").read_text(encoding="utf-8").strip()
        d = root / run / "llm_debug"
        d.mkdir(parents=True, exist_ok=True)
        seq = len(list(d.glob(f"{label}_*_{kind}.txt"))) + 1
        (d / f"{label}_{seq}_{kind}.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass


def run_sync(agent: Agent, prompt: str):
    """执行 agent.run_sync，对瞬态网络错误（连接/超时/限流）指数退避重试。

    OpenRouter 免费档上游限流与跨境网络抖动常见，节点统一经本函数调用。
    每次调用打点(输出类型/重试轮次/耗时/prompt与结果规模)——阶段日志的 LLM 观测面。
    输出校验不过(UnexpectedModelBehavior)单独走快速通道：确定性错误不指数退避，
    短延迟重试 _VALIDATION_RETRIES 次，仍败即抛（交外层 _PLAN_RETRY 修正）。
    """
    label = getattr(getattr(agent, "output_type", None), "__name__", "llm")
    delay = 10.0
    for attempt in range(_TRANSIENT_RETRIES):
        t0 = time.monotonic()
        log.info("[llm] %s 第%d次调用 prompt≈%d字符 …", label, attempt + 1, len(prompt))
        _dump_llm_io(label, "prompt", prompt)
        try:
            result = agent.run_sync(prompt)
            out = getattr(result, "output", None)
            payload = out.model_dump_json(indent=2) if hasattr(out, "model_dump_json") else ""
            _dump_llm_io(label, "output", payload)          # 序列化一次,转储与规模共用
            log.info("[llm] %s 完成 %.1fs 输出≈%d字符(全文见 llm_debug/)", label,
                     time.monotonic() - t0, len(payload))
            return result
        except UnexpectedModelBehavior:
            if attempt >= _VALIDATION_RETRIES - 1:
                raise
            log.warning("[llm] %s 输出校验不过 %.1fs,%.0fs 后快速重试", label,
                        time.monotonic() - t0, _VALIDATION_RETRY_DELAY_S)
            time.sleep(_VALIDATION_RETRY_DELAY_S)
        except _TRANSIENT_ERRORS:
            log.warning("[llm] %s 瞬态错误 %.1fs 后重试", label, time.monotonic() - t0)
            if attempt == _TRANSIENT_RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")
