"""make_agent 工厂：output_type / system_prompt / retries / 请求设置透传给 PydanticAI Agent。"""
from biaoshu_gen.models import llm_model_settings, make_agent
from biaoshu_gen.schemas import GlobalFacts


def test_make_agent_builds_agent_with_output_type():
    agent = make_agent(GlobalFacts, system_prompt="你是投标助手")
    assert agent.output_type is GlobalFacts


def test_llm_model_settings():
    """LLM_THINKING / LLM_REASONING_EFFORT 映射：合法值注入（thinking 经 extra_body、
    reasoning_effort 走 pydantic-ai 原生字段直达请求体），空值/未知值不注入跟随默认。"""
    assert llm_model_settings("disabled", "") == {
        "extra_body": {"thinking": {"type": "disabled"}}}
    assert llm_model_settings("enabled", "high") == {
        "extra_body": {"thinking": {"type": "enabled"}}, "openai_reasoning_effort": "high"}
    assert llm_model_settings("", "low") == {"openai_reasoning_effort": "low"}
    assert llm_model_settings("", "") is None
    assert llm_model_settings("auto", "ultra") is None       # 未知值不注入


def test_run_sync_retries_on_model_behavior_error(monkeypatch):
    """校验不过(UnexpectedModelBehavior)走快速通道:确定性错误不指数退避,短延迟
    重试一次即成功,不再炸穿节点——fresh run 实测 SectionBody 因此失败过一次。"""
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    from biaoshu_gen.models import _TRANSIENT_ERRORS, run_sync

    assert UnexpectedModelBehavior not in _TRANSIENT_ERRORS      # 已与网络瞬态解耦

    calls = []
    monkeypatch.setattr("time.sleep", lambda s: None)

    class _Out:
        def model_dump_json(self, indent=None):
            return "{}"

    class _R:
        output = _Out()

    class _Agent:
        output_type = GlobalFacts

        def run_sync(self, prompt):
            calls.append(prompt)
            if len(calls) == 1:
                raise UnexpectedModelBehavior("Exceeded maximum output retries (2)")
            return _R()

    result = run_sync(_Agent(), "p")
    assert result.output.model_dump_json() == "{}"
    assert len(calls) == 2


def test_run_sync_gives_up_after_validation_retries(monkeypatch):
    """校验错误最多快速重试 _VALIDATION_RETRIES 次(共 _VALIDATION_RETRIES 次调用),
    不消耗网络瞬态的 4 轮指数退避。"""
    import pytest
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    from biaoshu_gen.models import _VALIDATION_RETRIES, run_sync

    calls = []
    monkeypatch.setattr("time.sleep", lambda s: None)

    class _Agent:
        output_type = GlobalFacts

        def run_sync(self, prompt):
            calls.append(prompt)
            raise UnexpectedModelBehavior("Exceeded maximum output retries (2)")

    with pytest.raises(UnexpectedModelBehavior):
        run_sync(_Agent(), "p")
    assert len(calls) == _VALIDATION_RETRIES


def test_run_sync_retries_on_malformed_response_body(monkeypatch):
    """HTTP 200 但响应体损坏(openrouter 免费档实测:JSON 截断在 char 1100)按瞬态
    重试——pydantic-ai 只包装 APIStatusError/APIConnectionError,JSONDecodeError
    裸穿重试网曾炸穿 review 阶段(2026-09-08 run-20260908-215413)。"""
    import json

    from biaoshu_gen.models import run_sync

    calls = []
    monkeypatch.setattr("time.sleep", lambda s: None)

    class _Out:
        def model_dump_json(self, indent=None):
            return "{}"

    class _R:
        output = _Out()

    class _Agent:
        output_type = GlobalFacts

        def run_sync(self, prompt):
            calls.append(prompt)
            if len(calls) == 1:
                raise json.JSONDecodeError("Expecting value", "{}\n{", 3)
            return _R()

    result = run_sync(_Agent(), "p")
    assert len(calls) == 2                       # 同一 prompt 重发,不炸穿节点
    assert result.output.model_dump_json() == "{}"


def test_malformed_body_counts_as_transient():
    """JSONDecodeError 必须在瞬态错误族内,否则 run_sync 的 except 网接不住。"""
    import json

    from biaoshu_gen.models import _TRANSIENT_ERRORS

    assert json.JSONDecodeError in _TRANSIENT_ERRORS
