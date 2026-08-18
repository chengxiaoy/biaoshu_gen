"""节点注册表：未实现的节点为 stub，实现后在 REAL_IMPORTS 处登记。"""
from collections.abc import Callable

from ..state import BidState

NodeFn = Callable[[BidState], dict]

NODE_NAMES = [
    "parse_tender", "extract_template", "facts", "outline",
    "body", "body_review",
    "fill_forms", "deviation_table", "commercial",
    "assemble", "review", "revise",
]


def _stub(name: str) -> NodeFn:
    def f(state: BidState) -> dict:
        raise NotImplementedError(f"节点 {name} 尚未实现")
    f.__name__ = f"{name}_stub"
    return f


DEFAULT_NODES: dict[str, NodeFn] = {n: _stub(n) for n in NODE_NAMES}

# --- 已实现节点登记（逐任务补充） ---
from .parse_tender import parse_tender_node          # noqa: E402
DEFAULT_NODES["parse_tender"] = parse_tender_node

from .extract_template import extract_template_node  # noqa: E402
DEFAULT_NODES["extract_template"] = extract_template_node


def get_nodes(overrides: dict[str, NodeFn] | None = None) -> dict[str, NodeFn]:
    nodes = dict(DEFAULT_NODES)
    nodes.update(overrides or {})
    return nodes
