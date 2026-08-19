"""投标人企业资料：表格填写节点所需字段，缺失时 mock 占位并回写 03_facts.yaml。"""
import sys

from .schemas import GlobalFacts, from_yaml_file, to_yaml_file
from .state import BidState, run_dir

# 缺失时的 mock 占位值（明显可识别，供用户人工替换）
_MOCK_BUSINESS: dict[str, str] = {
    "company_name": "某某科技有限公司（待替换）",
    "legal_person": "法定代表人（待替换）",
    "credit_code": "91100000MA0000000X（待替换）",
}


def ensure_business_fields(state: BidState) -> GlobalFacts:
    """确保 03_facts.yaml 含企业/法人/信用代码字段；缺失则写入 mock 占位并提示用户。"""
    yaml_path = run_dir(state) / "03_facts.yaml"
    facts = from_yaml_file(GlobalFacts, yaml_path) if yaml_path.exists() else (
        state.facts or GlobalFacts())
    changed = False
    for field, mock in _MOCK_BUSINESS.items():
        if not getattr(facts, field, ""):
            setattr(facts, field, mock)
            changed = True
    if changed:
        to_yaml_file(facts, yaml_path)
        print("⚠ 03_facts.yaml 缺少企业资料（公司名称/法人/信用代码），已写入 mock 占位值，"
              "请人工编辑替换后重跑 fill 阶段。", file=sys.stderr)
    return facts
