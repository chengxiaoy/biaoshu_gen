from biaoshu_gen.config import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.llm_model == "deepseek-chat"
    assert s.llm_base_url == "https://api.deepseek.com"
    assert s.body_review_max_rounds == 2
    assert s.revise_max_rounds == 2
    assert s.word_tolerance == 0.5
    assert str(s.data_dir) == "data"


def test_settings_reads_generic_env(monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-or-test")
    monkeypatch.setenv("MODEL_NAME", "poolside/laguna-s-2.1:free")
    monkeypatch.setenv("BASE_URL", "https://openrouter.ai/api/v1")
    s = Settings(_env_file=None)
    assert s.llm_api_key == "sk-or-test"
    assert s.llm_model == "poolside/laguna-s-2.1:free"
    assert s.llm_base_url == "https://openrouter.ai/api/v1"


def test_settings_falls_back_to_deepseek_apikey(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_APIKEY", "sk-apikey-only")
    s = Settings(_env_file=None)
    assert s.llm_api_key == "sk-apikey-only"


def test_settings_prefers_generic_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-generic")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    s = Settings(_env_file=None)
    assert s.llm_api_key == "sk-generic"


def test_base_url_strips_completions_path():
    s = Settings(_env_file=None, llm_base_url="https://openrouter.ai/api/v1/chat/completions")
    assert s.llm_base_url == "https://openrouter.ai/api/v1"
    s2 = Settings(_env_file=None, llm_base_url="https://api.deepseek.com")
    assert s2.llm_base_url == "https://api.deepseek.com"


def test_settings_reads_harness_env(monkeypatch):
    monkeypatch.setenv("HARNESS_API_KEY", "sk-harness")
    monkeypatch.setenv("HARNESS_BASE_URL", "https://open.bigmodel.cn/api/anthropic")
    monkeypatch.setenv("HARNESS_MODEL", "glm-4.6")
    s = Settings(_env_file=None)
    assert s.harness_api_key == "sk-harness"
    assert s.harness_base_url == "https://open.bigmodel.cn/api/anthropic"
    assert s.harness_model == "glm-4.6"


def test_harness_defaults_empty():
    s = Settings(_env_file=None)
    assert s.harness_api_key == ""
    assert s.harness_base_url == ""
    assert s.harness_model == ""


def test_harness_base_url_normalizes_trailing_paths():
    """带 /v1/messages 或 /v1 尾巴都归一为 Anthropic base（CLI 自拼 /v1/messages）。"""
    s1 = Settings(_env_file=None, harness_base_url="https://openrouter.ai/api/v1/messages")
    assert s1.harness_base_url == "https://openrouter.ai/api"
    s2 = Settings(_env_file=None, harness_base_url="https://openrouter.ai/api/v1")
    assert s2.harness_base_url == "https://openrouter.ai/api"
    s3 = Settings(_env_file=None, harness_base_url="https://api.anthropic.com")
    assert s3.harness_base_url == "https://api.anthropic.com"
    s4 = Settings(_env_file=None, harness_base_url="")
    assert s4.harness_base_url == ""


def test_anthropic_base_url_property_removed():
    """派生逻辑（OpenRouter 双协议耦合）已删，不得再出现。"""
    assert not hasattr(Settings(_env_file=None), "anthropic_base_url")
