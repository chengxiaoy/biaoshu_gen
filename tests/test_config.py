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
    s = Settings()
    assert s.deepseek_api_key == "sk-test"
