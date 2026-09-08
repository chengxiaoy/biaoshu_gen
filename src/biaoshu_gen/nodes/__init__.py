"""节点注册表：全部 12 节点已实现，get_nodes 供 build_graph 使用。"""
from collections.abc import Callable

from ..state import BidState

NodeFn = Callable[[BidState], dict]

NODE_NAMES = [
    "parse_tender", "extract_template", "split_template", "facts", "outline",
    "body", "body_review",
    "fill_forms", "deviation_table",
    "assemble", "review", "revise",
]

from .parse_tender import parse_tender_node          # noqa: E402
from .extract_template import extract_template_node  # noqa: E402
from .split_template import split_template_node      # noqa: E402
from .facts import facts_node                        # noqa: E402
from .outline import outline_node                    # noqa: E402
from .rich_body import rich_body_node                # noqa: E402  # body 节点已由 rich_body 替换（图表生成 + 二级粒度并发）
from .body_review import body_review_node            # noqa: E402
from .fill_forms import fill_forms_node              # noqa: E402
from .deviation_table import deviation_table_node    # noqa: E402
from .assemble import assemble_node                  # noqa: E402
from .review import review_node                      # noqa: E402
from .revise import revise_node                      # noqa: E402

DEFAULT_NODES: dict[str, NodeFn] = {
    "parse_tender": parse_tender_node,
    "extract_template": extract_template_node,
    "split_template": split_template_node,
    "facts": facts_node,
    "outline": outline_node,
    "body": rich_body_node,
    "body_review": body_review_node,
    "fill_forms": fill_forms_node,
    "deviation_table": deviation_table_node,
    "assemble": assemble_node,
    "review": review_node,
    "revise": revise_node,
}


def get_nodes(overrides: dict[str, NodeFn] | None = None) -> dict[str, NodeFn]:
    nodes = dict(DEFAULT_NODES)
    nodes.update(overrides or {})
    return nodes


def soft_fill_fail(name: str, field_default: dict):
    """fill 节点软失败包装:异常捕获后写 06_fill/<节点>.error.log,置空输出放行流程。

    用户裁决:fill 节点失败不阻塞管线(不重跑、不中断),失败信息记 log,
    assemble 对缺失产物天然容错(用原始 part)。
    """
    import logging
    import traceback

    from ..state import write_node_error

    log = logging.getLogger(__name__)

    def wrap(fn: NodeFn) -> NodeFn:
        def node(state: BidState) -> dict:
            try:
                return fn(state)
            except Exception:
                errfile = write_node_error(state, name, traceback.format_exc())
                log.exception("%s 节点失败,已记 %s,流程继续(产物置空)", name, errfile)
                return dict(field_default)
        node.__name__ = fn.__name__
        return node
    return wrap


_fill_soft = {
    "fill_forms": ({"forms_docx_path": ""}),
    "deviation_table": ({"deviation_docx_path": ""}),
}
for _k, _d in _fill_soft.items():
    DEFAULT_NODES[_k] = soft_fill_fail(_k, _d)(DEFAULT_NODES[_k])
