from biaoshu_gen.config import Settings


def test_settings_defaults():
    s = Settings()
    assert s.deepseek_model == "deepseek-chat"
    assert s.deepseek_base_url == "https://api.deepseek.com"
    assert s.body_review_max_rounds == 2
    assert s.revise_max_rounds == 2
    assert s.word_tolerance == 0.2
    assert str(s.data_dir) == "data"


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    s = Settings(_env_file=None)
    assert s.deepseek_api_key == "sk-test"


def test_settings_falls_back_to_deepseek_apikey(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_APIKEY", "sk-apikey-only")
    s = Settings(_env_file=None)
    assert s.deepseek_api_key == "sk-apikey-only"


def test_settings_prefers_deepseek_api_key_when_both_set(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-underscore")
    monkeypatch.setenv("DEEPSEEK_APIKEY", "sk-no-underscore")
    s = Settings(_env_file=None)
    assert s.deepseek_api_key == "sk-underscore"
