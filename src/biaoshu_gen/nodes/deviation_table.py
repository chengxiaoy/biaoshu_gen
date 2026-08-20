"""节点 8：偏离表（harness 按响应模板格式填写）。

响应模板含偏离表模板才执行；逻辑收敛于 fill_context.run_fill_node。
"""
from ..fill_context import SECTION_KEYWORDS, run_fill_node
from ..prompts.deviation_table import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def deviation_table_node(state: BidState) -> dict:
    return run_fill_node(
        state, subdir="06_fill/deviation", output_field="deviation_docx_path",
        output_name="deviation.docx",
        extra_inputs=[(run_dir(state) / "01_parse" / "requirements.yaml", "requirements.yaml")],
        system=SYSTEM, build_user_prompt=build_user_prompt,
        required_keyword=SECTION_KEYWORDS["deviation"][0],
    )
