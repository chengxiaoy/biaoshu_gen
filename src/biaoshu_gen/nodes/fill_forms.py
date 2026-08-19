"""节点 7：投标函+报价文件+货物一览表+资格证明文件（harness 从响应模板副本填写）。

与 deviation/commercial 策略一致：都以响应模板为格式依据在模板副本中填写；
无响应模板则跳过（无法保证格式一致性）。
"""
from ..business import ensure_business_fields
from ..harness import HarnessTask, prepare_agent_workspace, run_harness_task
from ..prompts.fill_forms import SYSTEM, build_user_prompt
from ..state import BidState, run_dir


def fill_forms_node(state: BidState) -> dict:
    if not state.template_docx_path:
        print("ℹ 无响应模板，跳过表格填写节点（无法保证格式一致性）。")
        return {"forms_docx_path": ""}
    facts = ensure_business_fields(state)       # 企业/法人/信用代码缺失则 mock 并回写 facts.yaml
    ws = prepare_agent_workspace(state, "06_fill/forms", [
        (run_dir(state) / "01_parse" / "metadata.yaml", "metadata.yaml"),
        (run_dir(state) / "03_facts.yaml", "facts.yaml")])
    out = ws / "forms.docx"
    run_harness_task(HarnessTask(
        prompt=SYSTEM + "\n\n" + build_user_prompt(
            str(out), facts.company_name, facts.legal_person, facts.credit_code),
        cwd=ws, expected_outputs=[out]))
    return {"forms_docx_path": str(out)}
