"""直驱重跑 commercial(主桶+附加段)并就地 assemble 出 v2——绕过 checkpoint 恢复语义。

用法: python -u data/extract_artifacts/rerun_commercial.py <run-id>
"""
import logging
import sqlite3
import sys

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from langgraph.checkpoint.sqlite import SqliteSaver

from biaoshu_gen.graph import build_graph
from biaoshu_gen.nodes.assemble import assemble_node
from biaoshu_gen.nodes.commercial import commercial_node
from biaoshu_gen.state import BidState

rid = sys.argv[1] if len(sys.argv) > 1 else "run-20260827-software"
conn = sqlite3.connect(f"data/runs/{rid}/checkpoint.sqlite", check_same_thread=False)
g = build_graph(checkpointer=SqliteSaver(conn))
vals = g.get_state({"configurable": {"thread_id": rid}}).values
fields = BidState.model_fields.keys()
state = BidState(**{k: v for k, v in vals.items() if k in fields and v is not None})
print("state 载入完成:", rid, flush=True)

updates = commercial_node(state)
print("commercial 结果:", {k: str(v)[:60] for k, v in updates.items()}, flush=True)

merged = state.model_copy(update={
    "commercial_docx_path": updates.get("commercial_docx_path", state.commercial_docx_path),
    "extra_products_commercial": updates.get("extra_products_commercial") or {},
    "draft_version": state.draft_version,   # v2 = +1
})
final = assemble_node(merged)
print("assemble 产物:", final["draft_docx_path"], flush=True)
