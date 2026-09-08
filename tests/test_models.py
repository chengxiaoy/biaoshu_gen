"""make_agent 工厂：output_type / system_prompt / retries 透传给 PydanticAI Agent。"""
from biaoshu_gen.models import make_agent, thinking_model_settings
from biaoshu_gen.schemas import GlobalFacts


def test_make_agent_builds_agent_with_output_type():
    agent = make_agent(GlobalFacts, system_prompt="你是投标助手")
    assert agent.output_type is GlobalFacts


def test_thinking_model_settings():
    """LLM_THINKING 映射：enabled/disabled 经 extra_body 注入，其余不注入。"""
    off = thinking_model_settings("disabled")
    assert off == {"extra_body": {"thinking": {"type": "disabled"}}}
    on = thinking_model_settings("enabled")
    assert on == {"extra_body": {"thinking": {"type": "enabled"}}}
    assert thinking_model_settings("") is None
    assert thinking_model_settings("auto") is None


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
