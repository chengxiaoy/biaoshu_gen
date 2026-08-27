"""make_agent 工厂：output_type / system_prompt / retries 透传给 PydanticAI Agent。"""
from biaoshu_gen.models import make_agent
from biaoshu_gen.schemas import GlobalFacts


def test_make_agent_builds_agent_with_output_type():
    agent = make_agent(GlobalFacts, system_prompt="你是投标助手")
    assert agent.output_type is GlobalFacts


def test_run_sync_retries_on_model_behavior_error(monkeypatch):
    """输出两次校验不过(UnexpectedModelBehavior)按瞬态处理:重新采样一次即成功,
    不再炸穿节点——fresh run 实测 SectionBody 因此失败过一次。"""
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    from biaoshu_gen.models import _TRANSIENT_ERRORS, run_sync

    assert UnexpectedModelBehavior in _TRANSIENT_ERRORS          # 已纳入可重试集合

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
