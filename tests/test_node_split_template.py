import json
from pathlib import Path

import pytest
from docx import Document
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from biaoshu_gen.nodes import split_template as st
from biaoshu_gen.state import BidState, run_dir

_SECTIONS = [
    "一、磋商响应声明", "二、供应商资格证明文件", "三、保证金（本项目无须提供）",
    "四、报价表及分项价格表", "五、货物说明一览表", "六、项目实施方案",
    "七、合同条款偏离表", "八、采购需求偏离表", "九、类似业绩",
]


def _titled_tpl(path: Path) -> None:
    """带 Heading 样式的响应模板:前言 + 九个二级节,偏离节下带表。"""
    doc = Document()
    doc.add_paragraph("第五章 响应文件组成")
    for title in _SECTIONS:
        doc.add_heading(title, level=2)
        if "偏离表" in title:
            t = doc.add_table(rows=2, cols=2)
            t.cell(0, 0).text = "序号"
            t.cell(0, 1).text = "偏离说明"
        else:
            doc.add_paragraph(f"{title} 正文。")
    doc.save(path)


def _state(tmp_path: Path, monkeypatch) -> BidState:
    monkeypatch.chdir(tmp_path)
    tpl = tmp_path / "tpl.docx"
    _titled_tpl(tpl)
    ws = tmp_path / "run-1" / "02_template"
    ws.mkdir(parents=True)
    tpl_final = ws / "标书模板.docx"
    tpl_final.write_bytes(tpl.read_bytes())
    return BidState(run_id="run-1", tender_path=str(tpl),
                    template_docx_path=str(tpl_final))


def test_split_by_heading_rules(tmp_path, monkeypatch):
    state = _state(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise AssertionError("有标题模板不应调用 LLM")
    monkeypatch.setattr(st, "make_agent", boom)

    updates = st.split_template_node(state)
    parts = updates["template_parts"]
    assert set(parts) == {"deviation", "technical", "forms", "commercial"}

    def texts(bucket: str) -> list[str]:
        return [p.text for p in Document(parts[bucket]).paragraphs if p.text.strip()]

    assert texts("deviation") == ["七、合同条款偏离表", "八、采购需求偏离表"]
    assert len(Document(parts["deviation"]).tables) == 2
    assert texts("technical") == ["六、项目实施方案", "六、项目实施方案 正文。"]
    assert texts("forms") == ["一、磋商响应声明", "一、磋商响应声明 正文。",
                              "二、供应商资格证明文件", "二、供应商资格证明文件 正文。",
                              "四、报价表及分项价格表", "四、报价表及分项价格表 正文。",
                              "五、货物说明一览表", "五、货物说明一览表 正文。"]
    assert texts("commercial") == ["第五章 响应文件组成",
                                   "三、保证金（本项目无须提供）", "三、保证金（本项目无须提供） 正文。",
                                   "九、类似业绩", "九、类似业绩 正文。"]

    manifest = st.read_parts_yaml(run_dir(state))
    # parts.yaml:order 按文档原序(前言归 commercial 故其居首),sections 记录标题
    assert manifest["order"] == ["commercial", "forms", "technical", "deviation"]
    assert "七、合同条款偏离表" in manifest["parts"]["deviation"]["sections"]


def test_split_untitled_template_via_llm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tpl = tmp_path / "tpl.docx"
    doc = Document()
    for text in ("一、磋商响应声明", "投标函正文。", "六、项目实施方案",
                 "方案正文。", "七、合同条款偏离表"):
        doc.add_paragraph(text)                     # 全普通段落,无 Heading 样式
    doc.save(tpl)
    ws = tmp_path / "run-1" / "02_template"
    ws.mkdir(parents=True)
    tpl_final = ws / "标书模板.docx"
    tpl_final.write_bytes(tpl.read_bytes())
    state = BidState(run_id="run-1", tender_path=str(tpl),
                     template_docx_path=str(tpl_final))

    calls: list[str] = []

    def make(output_type, system_prompt, retries=2):
        def fn(messages, info: AgentInfo):
            calls.append(messages[-1].parts[-1].content)
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            payload = {"spans": [
                {"start_index": 0, "end_index": 2, "bucket": "forms"},
                {"start_index": 2, "end_index": 4, "bucket": "technical"},
                {"start_index": 4, "end_index": None, "bucket": "deviation"},
            ]}
            return ModelResponse(parts=[ToolCallPart(tool_name=tool, args=json.dumps(payload))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(st, "make_agent", make)
    updates = st.split_template_node(state)
    parts = updates["template_parts"]

    def texts(bucket: str) -> list[str]:
        return [p.text for p in Document(parts[bucket]).paragraphs if p.text.strip()]

    assert texts("forms") == ["一、磋商响应声明", "投标函正文。"]
    assert texts("technical") == ["六、项目实施方案", "方案正文。"]
    assert texts("deviation") == ["七、合同条款偏离表"]
    assert parts.get("commercial", "") == ""               # 空 bucket 不落文件
    assert len(calls) == 1                                 # 单次 LLM 调用


def test_split_llm_retry_on_bad_span(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tpl = tmp_path / "tpl.docx"
    doc = Document()
    for text in ("一、磋商响应声明", "七、合同条款偏离表"):
        doc.add_paragraph(text)
    doc.save(tpl)
    ws = tmp_path / "run-1" / "02_template"
    ws.mkdir(parents=True)
    (ws / "标书模板.docx").write_bytes(tpl.read_bytes())
    state = BidState(run_id="run-1", tender_path=str(tpl), template_docx_path=str(ws / "标书模板.docx"))

    calls: list[str] = []

    def make(output_type, system_prompt, retries=2):
        def fn(messages, info: AgentInfo):
            calls.append(messages[-1].parts[-1].content)
            tool = info.output_tools[0].name if info.output_tools else "final_result"
            payload = ({"spans": [{"start_index": 99, "bucket": "forms"}]} if len(calls) == 1
                       else {"spans": [{"start_index": 0, "bucket": "forms"}]})
            return ModelResponse(parts=[ToolCallPart(tool_name=tool, args=json.dumps(payload))])
        return Agent(model=FunctionModel(fn), output_type=output_type,
                     system_prompt=system_prompt, retries=retries)

    monkeypatch.setattr(st, "make_agent", make)
    st.split_template_node(state)
    assert len(calls) == 2 and "校验" in calls[1]
