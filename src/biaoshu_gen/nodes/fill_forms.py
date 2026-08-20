"""节点 7：投标函+报价文件+货物一览表+资格证明文件（harness 从响应模板副本填写）。

响应模板为格式依据；无模板则跳过。逻辑收敛于 fill_context.run_fill_node。
"""
from ..business import ensure_business_fields
from ..fill_context import run_fill_node
from ..prompts.fill_forms import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def fill_forms_node(state: BidState) -> dict:
    facts = ensure_business_fields(state)       # 企业/法人/信用代码缺失则 mock 并回写 facts.yaml

    def prompt(output: str) -> str:
        return build_user_prompt(output, facts.company_name, facts.legal_person,
                                 facts.credit_code)

    return run_fill_node(
        state, subdir="06_fill/forms", output_field="forms_docx_path",
        output_name="forms.docx",
        extra_inputs=[(run_dir(state) / "01_parse" / "metadata.yaml", "metadata.yaml"),
                      (run_dir(state) / "03_facts.yaml", "facts.yaml")],
        system=SYSTEM, build_user_prompt=prompt)
