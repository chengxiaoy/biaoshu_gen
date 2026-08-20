"""单一 StateGraph：严格对应设计文档全局流程图，含两条条件回边。"""
from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .config import get_settings
from .nodes import NODE_NAMES, NodeFn, get_nodes
from .state import BidState


@dataclass(frozen=True)
class StageSpec:
    members: tuple[str, ...]
    end_nodes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.end_nodes:
            object.__setattr__(self, "end_nodes", self.members)


STAGES = {
    "parse":    StageSpec(("parse_tender",)),
    "template": StageSpec(("extract_template",)),
    "facts":    StageSpec(("facts",)),
    "outline":  StageSpec(("outline",)),
    "body":     StageSpec(("body", "body_review"), ("body_review",)),
    "fill":     StageSpec(("fill_forms", "deviation_table", "commercial")),
    "assemble": StageSpec(("assemble",)),
    "review":   StageSpec(("review",)),
    "revise":   StageSpec(("revise",)),
}
STAGE_ORDER = ["parse", "template", "facts", "outline", "body",
               "fill", "assemble", "review", "revise"]

FILL_NODES = ["fill_forms", "deviation_table", "commercial"]


def route_after_body_review(state: BidState) -> str | list[str]:
    s = get_settings()
    if not state.body_review_passed and state.body_review_rounds < s.body_review_max_rounds:
        return "body"
    return FILL_NODES


def route_after_review(state: BidState) -> str:
    s = get_settings()
    if state.review_passed:
        return END
    if state.revision_round < s.revise_max_rounds:
        return "revise"
    return END


def build_graph(node_overrides: dict[str, NodeFn] | None = None,
                checkpointer=None) -> CompiledStateGraph:
    builder = StateGraph(BidState)
    for name, fn in get_nodes(node_overrides).items():
        builder.add_node(name, fn)
    builder.add_edge(START, "parse_tender")
    for a, b in [("parse_tender", "extract_template"), ("extract_template", "facts"),
                 ("facts", "outline"), ("outline", "body"), ("body", "body_review")]:
        builder.add_edge(a, b)
    # langgraph 0.6.11：无 path_map 时运行时按返回值逐元素路由（list 亦可），
    # 但 get_graph() 不解析分支目标（拓扑断言看不到边），故显式给 path_map。
    builder.add_conditional_edges(
        "body_review", route_after_body_review,
        {"body": "body", "fill_forms": "fill_forms",
         "deviation_table": "deviation_table", "commercial": "commercial"})
    for n in FILL_NODES:
        builder.add_edge(n, "assemble")
    builder.add_edge("assemble", "review")
    builder.add_conditional_edges(
        "review", route_after_review, {"revise": "revise", END: END})
    builder.add_edge("revise", "review")
    return builder.compile(checkpointer=checkpointer)
