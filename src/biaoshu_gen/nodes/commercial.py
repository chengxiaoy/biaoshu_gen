"""节点 9：商务响应文件（harness 按响应模板格式填写）。

响应模板含"商务部分"才执行；逻辑收敛于 fill_context.run_fill_node。
"""
from ..fill_context import SECTION_KEYWORDS, run_fill_node
from ..prompts.commercial import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def commercial_node(state: BidState) -> dict:
    return run_fill_node(
        state, subdir="06_fill/commercial", output_field="commercial_docx_path",
        output_name="commercial.docx",
        extra_inputs=[(run_dir(state) / "01_parse" / "scoring.yaml", "scoring.yaml")],
        system=SYSTEM, build_user_prompt=build_user_prompt,
        required_keyword=SECTION_KEYWORDS["commercial"][0],
    )
