"""KnowledgeBaseV2 真实 e2e：连本地 RAGFlow（与 tests/test_ragflow.py 同一部署）。

流程：建 e2e 专属 dataset -> load 上传并解析（md + OCR 图片）-> search / search_image
-> chat 问答 -> 清理。server 未启动时整文件 skip；断言的 300W 等特征值来自测试
自己上传的文档。
"""
import subprocess
import sys
from pathlib import Path

import pytest
import requests
from ragflow_sdk import RAGFlow

from biaoshu_gen.config import get_settings
from biaoshu_gen.kb_v2 import KnowledgeBaseV2

pytestmark = pytest.mark.e2e   # 默认排除；显式 pytest -m e2e 运行

KB_NAME = "biaoshu-e2e-kb"
CHAT_NAME = "biaoshu-e2e-assistant"

DOC_TEXT = """# 硬件产品规格（e2e 测试）

X100 边缘计算盒子：功率 300W，工作温度 -20℃~60℃，质保三年，支持国产化操作系统。

X200 边缘计算盒子：功率 500W，支持 5G 上网，质保五年，随机附赠导轨套件。
"""


def _server_up() -> bool:
    settings = get_settings()
    try:
        requests.get(settings.ragflow_base_url, timeout=2)
        return True
    except requests.RequestException:
        return False


if not _server_up():
    pytest.skip("RAGFlow server 未启动（RAGFLOW_BASE_URL）", allow_module_level=True)


def _make_spec_png(path: Path) -> None:
    """System.Drawing 生成带大号粗体文字的 PNG（给 deepdoc OCR 认），仅 Windows。"""
    script = f"""
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap(560, 160)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.Clear([System.Drawing.Color]::White)
$font = New-Object System.Drawing.Font('Arial', 40, [System.Drawing.FontStyle]::Bold)
$g.DrawString('X100 POWER 300W', $font, [System.Drawing.Brushes]::Black, 15, 50)
$bmp.Save('{path.as_posix()}', [System.Drawing.Imaging.ImageFormat]::Png)
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", script],
                   check=True, timeout=60, capture_output=True)


def _cleanup(rag: RAGFlow) -> None:
    """清掉上次可能残留的 e2e 资源（同名 dataset / 助手）。

    不用 name 过滤参数：该 server 版本对不存在的名字抛权限错误而非返回空。
    """
    for ds in rag.list_datasets(page_size=100):
        if ds.name == KB_NAME:
            rag.delete_datasets(ids=[ds.id])
    for chat in rag.list_chats(page_size=100):
        if chat.name == CHAT_NAME:
            rag.delete_chats(ids=[chat.id])


@pytest.fixture(scope="module")
def e2e(tmp_path_factory) -> "tuple[KnowledgeBaseV2, RAGFlow]":
    settings = get_settings()
    rag = RAGFlow(api_key=settings.ragflow_api_key, base_url=settings.ragflow_base_url)
    _cleanup(rag)

    kb = KnowledgeBaseV2(dataset_name=KB_NAME, rag=rag)

    d = tmp_path_factory.mktemp("e2e_kb")
    (d / "规格.md").write_text(DOC_TEXT, encoding="utf-8")
    has_png = sys.platform == "win32"
    if has_png:
        _make_spec_png(d / "规格.png")                        # OCR 图片：search_image 用
    uploaded = kb.load(d, wait=True)                          # 阻塞到解析完成，chunk 可检索
    assert uploaded == 2 if has_png else uploaded == 1

    # 建助手必须在 dataset 有已解析文件之后（实测：空库建助手报 doesn't own parsed file）
    kb._rag.create_chat(name=CHAT_NAME, dataset_ids=[kb._dataset.id],
                        llm_id=settings.ragflow_llm_id or None)
    kb._chat_assistant = next(c for c in rag.list_chats(page_size=100)
                              if c.name == CHAT_NAME)         # e2e 全程复用同一个助手

    yield kb, rag
    _cleanup(rag)


def test_e2e_load_indexed_documents(e2e):
    kb, _ = e2e
    docs = kb._dataset.list_documents(page_size=10)
    assert sorted(d.name for d in docs) == ["规格.md", "规格.png"]
    assert all(d.run.upper() == "DONE" for d in docs)         # 解析到终态
    assert all(d.chunk_count > 0 for d in docs)               # 确实切出了 chunk


def test_e2e_search_hits_uploaded_fact(e2e):
    kb, _ = e2e
    hits = kb.search("X100 边缘计算盒子 功率", top_k=5)
    assert hits, "混合检索无结果——检查解析/embedding 是否就绪"
    assert any("300W" in h.text for h in hits)
    # 图片文档的 OCR 文本也含 X100，允许两个来源
    assert all(h.source in ("规格.md", "规格.png") for h in hits)


def test_e2e_search_misses_absent_topic(e2e):
    kb, _ = e2e
    hits = kb.search("量子计算机的制冷机参数")
    # 不强求零命中（阈值 0.2 下可能有低分牵连），只要求不要出现高分幻影
    assert all(h.score < 0.7 for h in hits)


def test_e2e_search_image_and_fetch_bytes(e2e):
    kb, _ = e2e
    hits = kb.search_image("X100 POWER 300W", top_k=5)
    assert hits, "无 image 块召回——检查部署解析管道是否开了图片提取（doc_type=image）"
    assert all(h.url.endswith(f"/api/v1/documents/images/{h.image_id}") for h in hits)

    data = kb.get_image_bytes(hits[0])
    assert len(data) > 100                                    # 真实图片字节
    assert data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"  # PNG/JPEG 魔数


def test_e2e_search_excludes_knowledge_compilation():
    """开 RAPTOR 的库（本机 kw_raptor）：search 不得召回树摘要 JSON 块。

    只读不改该库；库不存在则跳过。回归：search 走 raw /retrieval 时必须带
    include_knowledge_compilation=false（默认会 top-10 全是 {"name":...} 块）。
    """
    settings = get_settings()
    rag = RAGFlow(api_key=settings.ragflow_api_key, base_url=settings.ragflow_base_url)
    if not any(d.name == "kw_raptor" for d in rag.list_datasets(page_size=100)):
        pytest.skip("本机无 kw_raptor 库")
    kb = KnowledgeBaseV2(dataset_name="kw_raptor", rag=rag)
    hits = kb.search("BLIP 预训练超参数", top_k=10)
    assert hits
    assert all(not h.text.lstrip().startswith('{"') for h in hits), \
        "检索结果混入知识编译衍生块（entity/relation JSON）"


def test_e2e_chat_answers_from_knowledge_base(e2e):
    kb, _ = e2e
    # naive：普通检索直答（当前部署上验证可用）
    answer = kb.chat("X100 边缘计算盒子的功率是多少瓦？", think="naive")
    assert answer.strip(), "chat 返回了空回答"
    assert "300" in answer                                    # 事实必须来自知识库


@pytest.mark.xfail(
    reason="服务端 agentic 管线 bug：研究阶段 verdict=SUFFICIENT 且有 passages，"
           "但 synthesis 阶段 kbinfos 为空触发兜底文案（见 ragflow_server.log "
           "'Research complete' 后 tool content 'Sorry! No relevant content'）；"
           "服务端修复后此测试转正",
    strict=False,
)
def test_e2e_chat_medium_agentic_answers(e2e):
    kb, _ = e2e
    # medium = agentic + SCA（设计文档的 Agentic RAG 主路径）
    answer = kb.chat("X100 边缘计算盒子的功率是多少瓦？", think="medium")
    assert "300" in answer


def test_e2e_chat_multi_turn_memory(e2e):
    """多轮：带 session_id 追问「它」，服务端拼上一轮历史后应能解析指代。"""
    kb, _ = e2e
    kb.chat("X100 边缘计算盒子的功率是多少？", think="naive")
    assert kb.last_session_id, "响应未回传 session_id"
    follow = kb.chat("那它的质保期是几年？", think="naive",
                     session_id=kb.last_session_id)
    assert "三" in follow                                         # X100 质保三年


def test_e2e_chat_fallback_for_absent_question(e2e):
    kb, _ = e2e
    # naive：普通检索直答，无 agentic
    answer = kb.chat("公司量子引力研究团队的负责人是谁？", think="naive")
    # 无关问题必须明确说知识库中没有，而不是编造。不同 prompt 兜底话术不同：
    # test_ragflow.py 的自定义 prompt 是 "not found in the dataset"，
    # RAGFlow 默认 prompt 是 "No relevant content was found in the knowledge base!"
    lowered = answer.lower()
    assert ("no relevant content" in lowered or "not found" in lowered
            or "没有" in answer or "未找到" in answer)
