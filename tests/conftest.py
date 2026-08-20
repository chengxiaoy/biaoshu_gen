"""测试基建：给 LLM 节点注入假模型的 Agent 工厂（PydanticAI FunctionModel）。

pydantic-ai 1.107.5 适配：FunctionModel 回调必须返回 ModelResponse（不能返回
dict/str），且 AgentInfo 无 output_type 字段，故经闭包捕获工厂收到的
output_type 来选择预设输出，并以 output tool 调用形式返回结构化结果。
"""
import json

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


def _last_user_content(messages) -> str:
    """取最近一条用户消息文本（供断言节点传入的 prompt）。"""
    last = messages[-1]
    content = getattr(last, "content", None)
    if content is None:
        content = next(
            (p.content for p in getattr(last, "parts", []) if isinstance(p, UserPromptPart)),
            "",
        )
    return str(content)


def _make_fake_agent(overrides: dict, default: dict, output_type, system_prompt: str, retries: int):
    async def fn(messages, info: AgentInfo):
        out = overrides.get(output_type, default)
        tool_name = info.output_tools[0].name if info.output_tools else "final_result"
        return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=json.dumps(out))])

    return Agent(model=FunctionModel(fn), output_type=output_type,
                 system_prompt=system_prompt, retries=retries)


@pytest.fixture
def fake_agent_factory():
    """用法：monkeypatch.setattr(node_mod, 'make_agent', fake_agent_factory({SomeType: {...}}))"""
    def _factory(overrides: dict, default: dict | None = None):
        def make(output_type, system_prompt, retries=2):
            return _make_fake_agent(overrides, default or {}, output_type,
                                    system_prompt, retries)
        return make
    return _factory
