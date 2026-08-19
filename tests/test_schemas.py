from pathlib import Path

import pytest

from biaoshu_gen.schemas import (
    GlobalFacts, InvalidationItem, Outline, OutlineNode, TocMap,
    from_yaml_file, to_yaml_file,
)


def test_invalidation_kind_validation():
    ok = InvalidationItem(kind="扣分项", requirement="质保期不足扣 2 分")
    assert ok.kind == "扣分项"
    with pytest.raises(Exception):
        InvalidationItem(kind="其他", requirement="x")


def test_yaml_roundtrip(tmp_path: Path):
    facts = GlobalFacts(schedule="90 天", staffing="项目经理 1 名",
                        software_metrics=["并发>=1000"], extra=["通过等保三级"])
    p = tmp_path / "03_facts.yaml"
    to_yaml_file(facts, p)
    assert p.read_text(encoding="utf-8").startswith("schedule:")
    assert from_yaml_file(GlobalFacts, p) == facts


def test_from_yaml_file_field_error(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("sections:\n- title: 章节\n  target_words: 五百\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        from_yaml_file(Outline, p)
    assert "target_words" in str(e.value)


def test_outline_node_tree():
    o = OutlineNode(title="总体方案")
    assert o.target_words == 0 and o.children == [] and o.description == ""
    tree = Outline(sections=[OutlineNode(id="1", title="章", children=[
        OutlineNode(id="1.1", title="节", children=[
            OutlineNode(id="1.1.1", title="小节", target_words=500)])])])
    leaves = tree.leaves()
    assert len(leaves) == 1 and leaves[0].id == "1.1.1" and leaves[0].target_words == 500


def test_toc_map_parse():
    tm = TocMap.model_validate({"assignments": [
        {"index": 1, "title": "评标办法", "categories": ["scoring", "invalidation"]}]})
    assert tm.assignments[0].categories == ["scoring", "invalidation"]


def test_outline_requires_sections():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Outline.model_validate({"sections": [], "total_words": 0})
    with pytest.raises(ValidationError):          # 省略字段同样拒绝（默认值不校验的坑）
        Outline.model_validate({"total_words": 0})
