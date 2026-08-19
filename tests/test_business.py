from biaoshu_gen.business import ensure_business_fields
from biaoshu_gen.schemas import GlobalFacts, from_yaml_file
from biaoshu_gen.state import BidState, run_dir


def test_ensure_business_fields_mocks_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1")
    facts = ensure_business_fields(state)
    assert facts.company_name and "待替换" in facts.company_name
    assert facts.legal_person and facts.credit_code
    p = run_dir(state) / "03_facts.yaml"
    assert p.exists()
    loaded = from_yaml_file(GlobalFacts, p)
    assert loaded.company_name == facts.company_name
    assert loaded.credit_code == facts.credit_code


def test_ensure_business_fields_keeps_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = BidState(run_id="run-1")
    p = run_dir(state) / "03_facts.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("company_name: 真实公司\nlegal_person: 李四\ncredit_code: '9111'\n",
                 encoding="utf-8")
    facts = ensure_business_fields(state)
    assert facts.company_name == "真实公司"
    assert facts.legal_person == "李四"
    assert facts.credit_code == "9111"
    # 不覆盖已有值、不追加 mock
    assert "待替换" not in (run_dir(state) / "03_facts.yaml").read_text(encoding="utf-8")
