import sqlite3
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END

from biaoshu_gen import graph as g
from biaoshu_gen.state import BidState


def _saver(tmp_path: Path) -> SqliteSaver:
    return SqliteSaver(sqlite3.connect(tmp_path / "ck.db", check_same_thread=False))


def _fakes(spec: dict[str, int]) -> dict:
    """spec: 节点名 -> 该节点把 counter 字段 +1 的次数无意义；这里用闭包记录调用。"""
    calls: dict[str, int] = {}
    nodes = {}
    for name in g.NODE_NAMES:
        def make(n):
            def fn(state: BidState) -> dict:
                calls[n] = calls.get(n, 0) + 1
                if n == "body_review":
                    passed = calls["body"] >= 2        # 第 2 次正文后通过
                    return {"body_review_passed": passed,
                            "body_review_rounds": state.body_review_rounds + 1,
                            "body_feedback": "" if passed else "补充实施计划"}
                if n == "review":
                    passed = calls.get("revise", 0) >= 1   # 修改一轮后通过
                    return {"review_passed": passed}
                if n == "revise":
                    return {"revision_round": state.revision_round + 1,
                            "draft_version": state.draft_version + 1}
                return {}
            return fn
        nodes[name] = make(name)
    nodes["_calls"] = calls
    return nodes


def test_stage_specs_cover_all_nodes():
    members = [n for spec in g.STAGES.values() for n in spec.members]
    assert sorted(members) == sorted(g.NODE_NAMES)
    assert g.STAGE_ORDER[0] == "parse" and g.STAGE_ORDER[-1] == "revise"


def test_graph_topology():
    graph = g.build_graph(node_overrides={n: (lambda s: {}) for n in g.NODE_NAMES})
    # 用 get_graph 结构断言关键边
    structure = graph.get_graph()
    edges = {(e.source, e.target) for e in structure.edges}
    assert ("__start__", "parse_tender") in edges
    assert ("parse_tender", "extract_template") in edges
    assert ("body_review", "fill_forms") in edges
    assert ("fill_forms", "assemble") in edges
    assert ("revise", "review") in edges


def test_route_after_body_review_and_review():
    s = BidState(body_review_passed=False, body_review_rounds=1)
    assert g.route_after_body_review(s) == "body"
    s2 = BidState(body_review_passed=False, body_review_rounds=2)
    assert g.route_after_body_review(s2) == ["fill_forms", "deviation_table", "commercial"]
    s3 = BidState(review_passed=False, revision_round=0)
    assert g.route_after_review(s3) == "revise"
    s4 = BidState(review_passed=True)
    assert g.route_after_review(s4) == END
    s5 = BidState(review_passed=False, revision_round=2)
    assert g.route_after_review(s5) == END


def test_full_run_loops_converge(tmp_path: Path):
    fakes = _fakes({})
    overrides = {k: v for k, v in fakes.items() if k != "_calls"}
    graph = g.build_graph(node_overrides=overrides, checkpointer=_saver(tmp_path))
    init = {"run_id": "r1", "tender_path": "x.docx", "kb_dir": "kb"}
    graph.invoke(init, {"configurable": {"thread_id": "r1"}})
    calls = fakes["_calls"]
    assert calls["body"] == 2 and calls["body_review"] == 2      # 回环 1 次后通过
    assert calls["revise"] == 1 and calls["review"] == 2         # 修改 1 轮后通过
    assert calls["assemble"] == 1
