"""节点注册表：全部 12 节点已实现，get_nodes 供 build_graph 使用。"""
from collections.abc import Callable

from ..state import BidState

NodeFn = Callable[[BidState], dict]

NODE_NAMES = [
    "parse_tender", "extract_template", "facts", "outline",
    "body", "body_review",
    "fill_forms", "deviation_table", "commercial",
    "assemble", "review", "revise",
]

from .parse_tender import parse_tender_node          # noqa: E402
from .extract_template import extract_template_node  # noqa: E402
from .facts import facts_node                        # noqa: E402
from .outline import outline_node                    # noqa: E402
from .body import body_node                          # noqa: E402
from .body_review import body_review_node            # noqa: E402
from .fill_forms import fill_forms_node              # noqa: E402
from .deviation_table import deviation_table_node    # noqa: E402
from .commercial import commercial_node              # noqa: E402
from .assemble import assemble_node                  # noqa: E402
from .review import review_node                      # noqa: E402
from .revise import revise_node                      # noqa: E402

DEFAULT_NODES: dict[str, NodeFn] = {
    "parse_tender": parse_tender_node,
    "extract_template": extract_template_node,
    "facts": facts_node,
    "outline": outline_node,
    "body": body_node,
    "body_review": body_review_node,
    "fill_forms": fill_forms_node,
    "deviation_table": deviation_table_node,
    "commercial": commercial_node,
    "assemble": assemble_node,
    "review": review_node,
    "revise": revise_node,
}


def get_nodes(overrides: dict[str, NodeFn] | None = None) -> dict[str, NodeFn]:
    nodes = dict(DEFAULT_NODES)
    nodes.update(overrides or {})
    return nodes
