"""make_agent 工厂：output_type / system_prompt / retries 透传给 PydanticAI Agent。"""
from biaoshu_gen.models import make_agent
from biaoshu_gen.schemas import GlobalFacts


def test_make_agent_builds_agent_with_output_type():
    agent = make_agent(GlobalFacts, system_prompt="你是投标助手")
    assert agent.output_type is GlobalFacts
