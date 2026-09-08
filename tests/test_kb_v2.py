"""KnowledgeBaseV2 单测：fake ragflow_sdk 对象，不连真实 RAGFlow server。"""
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from biaoshu_gen.config import get_settings
from biaoshu_gen.kb_v2 import KbHit, KnowledgeBaseV2


# ---------- fakes ----------

@dataclass
class _FakeDoc:
    id: str
    name: str


@dataclass
class _FakeDataset:
    def __init__(self, id: str, name: str):
        self.id, self.name = id, name
        self.documents: dict[str, _FakeDoc] = {}   # name -> doc
        self.parsed: list[list[str]] = []
        self.async_parsed: list[list[str]] = []

    def list_documents(self, id=None, name=None, page=1, page_size=30):
        docs = list(self.documents.values())
        if id:
            docs = [d for d in docs if d.id == id]
        if name:
            docs = [d for d in docs if d.name == name]
        start = (page - 1) * page_size
        return docs[start:start + page_size]

    def upload_documents(self, document_list):
        docs = []
        for ele in document_list:
            doc = _FakeDoc(id=f"doc-{len(self.documents) + 1}", name=ele["display_name"])
            self.documents[doc.name] = doc
            docs.append(doc)
        return docs

    def parse_documents(self, ids):
        self.parsed.append(list(ids))

    def async_parse_documents(self, ids):
        self.async_parsed.append(list(ids))


class _FakeChat:
    """只保留 id/绑定/update：补全请求由 kb_v2 直接 raw post，不经 Chat 对象。"""

    def __init__(self, id: str):
        self.id = id
        self.name = ""
        self.dataset_ids: list[str] = []
        self.updates: list[dict] = []

    def update(self, update_message: dict):
        self.updates.append(dict(update_message))
        if "dataset_ids" in update_message:
            self.dataset_ids = list(update_message["dataset_ids"])


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeRAGFlow:
    """记录调用并按名字 get-or-create dataset/chat，行为对齐 ragflow_sdk 真实签名。"""

    def __init__(self, answer="answer"):
        self.datasets: dict[str, _FakeDataset] = {}
        self.chats: dict[str, _FakeChat] = {}
        self.chat_create_calls: list[dict] = []
        self.post_calls: list[tuple] = []
        self._answer = answer
        self._post_result: dict = {"code": 0, "data": {"chunks": []}}

    def post(self, path, json=None, stream=False, files=None):
        self.post_calls.append((path, json))
        if path == "/chat/completions":
            return _FakeResponse({"code": 0, "data": {"answer": self._answer,
                                                      "session_id": "sess-auto"}})
        # /retrieval：对齐真 server，按 page_size 截断返回
        chunks = self._post_result.get("data", {}).get("chunks", [])
        size = (json or {}).get("page_size")
        sliced = chunks[:size] if size else chunks
        return _FakeResponse({"code": self._post_result.get("code", 0),
                              "message": self._post_result.get("message"),
                              "data": {"chunks": sliced}})

    def list_datasets(self, page=1, page_size=100, **_):
        all_ds = list(self.datasets.values())
        start = (page - 1) * page_size
        return all_ds[start:start + page_size]

    def create_dataset(self, name, **_):
        ds = _FakeDataset(id=f"ds-{len(self.datasets) + 1}", name=name)
        self.datasets[name] = ds
        return ds

    def list_chats(self, page=1, page_size=100, **_):
        all_chats = list(self.chats.values())
        start = (page - 1) * page_size
        return all_chats[start:start + page_size]

    def create_chat(self, name, dataset_ids=None, **_):
        chat = _FakeChat(id=f"chat-{len(self.chats) + 1}")
        chat.name = name
        chat.dataset_ids = list(dataset_ids or [])
        self.chat_create_calls.append({"name": name, "dataset_ids": list(dataset_ids or [])})
        self.chats[name] = chat
        return chat


# ---------- 工具 ----------

def _make_kb_dir(tmp_path: Path) -> Path:
    kb = tmp_path / "company"
    kb.mkdir(exist_ok=True)
    (kb / "规格.md").write_text("型号 X100，功率 300W，质保三年。", encoding="utf-8")
    (kb / "案例.docx").write_bytes(b"PK fake docx")
    (kb / "logo.png").write_bytes(b"\x89PNG fake")
    (kb / "不支持的.xls").write_bytes(b"fake")
    (kb / ".隐藏.txt").write_text("skip", encoding="utf-8")
    return kb


def _kb(rag: _FakeRAGFlow, **kw) -> KnowledgeBaseV2:
    return KnowledgeBaseV2(rag=rag, **kw)


# ---------- init：dataset get-or-create ----------

def test_init_creates_dataset_when_missing():
    rag = _FakeRAGFlow()
    kb = _kb(rag)
    assert kb._dataset.name == "biaoshu-products"  # 默认名来自 settings（固定产品库）
    assert rag.datasets["biaoshu-products"] is kb._dataset


def test_init_reuses_existing_dataset():
    rag = _FakeRAGFlow()
    ds = rag.create_dataset("biaoshu-products")
    assert _kb(rag)._dataset is ds                # 同名复用，不重复建


# ---------- load ----------

def test_load_uploads_supported_files_and_parses(tmp_path):
    rag = _FakeRAGFlow()
    kb = _kb(rag)
    n = kb.load(_make_kb_dir(tmp_path))
    assert n == 3                                 # md/docx/png 进库，.xls 与 .隐藏.txt 被排除
    assert set(kb._dataset.documents) == {"规格.md", "案例.docx", "logo.png"}
    assert kb._dataset.parsed and len(kb._dataset.parsed[0]) == 3
    assert not kb._dataset.async_parsed           # 默认阻塞路径


def test_load_skips_same_name_files(tmp_path):
    rag = _FakeRAGFlow()
    kb = _kb(rag)
    kb.load(_make_kb_dir(tmp_path))
    assert kb.load(_make_kb_dir(tmp_path)) == 0   # 二次加载同名全跳过


def test_load_async_mode_and_missing_dir(tmp_path):
    rag = _FakeRAGFlow()
    kb = _kb(rag)
    assert kb.load(tmp_path / "不存在") == 0
    n = kb.load(_make_kb_dir(tmp_path), wait=False)
    assert n == 3 and kb._dataset.async_parsed and not kb._dataset.parsed


# ---------- search ----------

def test_search_maps_chunks_and_respects_top_k():
    rag = _FakeRAGFlow()
    rag._post_result = {"code": 0, "data": {"chunks": [
        _raw_chunk(content="功率 300W", doc_type="text", image_id="", sim=0.9, name="规格.md"),
        _raw_chunk(content="质保三年", doc_type="text", image_id="", sim=0.7, name="规格.md"),
        _raw_chunk(content="政务平台案例", doc_type="text", image_id="", sim=0.5, name="案例.docx"),
    ]}}
    kb = _kb(rag)
    hits = kb.search("功率 300W 的设备", top_k=2)
    assert hits == [KbHit(text="功率 300W", source="规格.md", score=0.9),
                    KbHit(text="质保三年", source="规格.md", score=0.7)]
    path, payload = rag.post_calls[0]
    assert path == "/retrieval"
    assert payload["dataset_ids"] == [kb._dataset.id]
    assert payload["page_size"] == 2
    assert payload["include_knowledge_compilation"] is False   # 服务端排除 RAPTOR 树等衍生块
    assert "similarity_threshold" not in payload               # 未传的参数留给服务端默认值


def test_search_extra_params_forwarded():
    rag = _FakeRAGFlow()
    _kb(rag).search("q", similarity_threshold=0.4, vector_similarity_weight=0.1)
    payload = rag.post_calls[0][1]
    assert payload["similarity_threshold"] == 0.4
    assert payload["vector_similarity_weight"] == 0.1


# ---------- chat ----------

def test_chat_returns_answer_and_binds_dataset():
    rag = _FakeRAGFlow(answer="建议采购 X100 三台")
    kb = _kb(rag)
    answer = kb.chat("采购清单建议")
    assert answer == "建议采购 X100 三台"
    created = rag.chat_create_calls[0]
    assert created == {"name": "biaoshu-assistant", "dataset_ids": [kb._dataset.id]}


def test_chat_posts_to_modern_endpoint_with_default_reasoning():
    rag = _FakeRAGFlow()
    kb = _kb(rag)
    kb.chat("q1")
    kb.chat("q2")
    assert [p for p, _ in rag.post_calls] == ["/chat/completions"] * 2   # 不再走废弃路由
    payloads = [j for _, j in rag.post_calls]
    assert all(p["reasoning"] == 2 for p in payloads)                    # 默认 medium
    assert all(p["chat_id"] == kb._chat_assistant.id for p in payloads)
    assert len(rag.chat_create_calls) == 1                               # 助手只建一次


def test_chat_think_levels_map_to_reasoning():
    rag = _FakeRAGFlow()
    kb = _kb(rag)
    for i, mode in enumerate(("naive", "low", "medium", "high", "ultra")):
        kb.chat(f"q-{mode}", think=mode)
        assert rag.post_calls[-1][1]["reasoning"] == i
    kb2 = _kb(rag, think="naive")                                 # 构造器默认可设
    kb2.chat("q")
    assert rag.post_calls[-1][1]["reasoning"] == 0


def test_chat_invalid_think_raises():
    rag = _FakeRAGFlow()
    with pytest.raises(ValueError, match="think"):
        _kb(rag).chat("q", think="extreme")


def test_init_rebinds_stale_chat_assistant():
    """残留助手绑着别的库时必须改绑当前库（实测踩坑：错绑导致检索永远落空）。"""
    rag = _FakeRAGFlow()
    stale = rag.create_chat("biaoshu-assistant", dataset_ids=["ds-other"])
    kb = _kb(rag)
    assert kb._chat_assistant is None
    kb.chat("q")
    assert stale.updates == [{"dataset_ids": [kb._dataset.id]}]
    assert stale.dataset_ids == [kb._dataset.id]


def test_chat_extra_kwargs_override_reasoning():
    rag = _FakeRAGFlow()
    kb = _kb(rag)
    kb.chat("q", reasoning=3)                                     # 调用方显式 reasoning 优先
    assert rag.post_calls[-1][1]["reasoning"] == 3
    kb.chat("q2", temperature=0.2)
    payload = rag.post_calls[-1][1]
    assert payload["temperature"] == 0.2
    assert payload["reasoning"] == 2                              # 未显式传时仍是默认档


def test_chat_session_roundtrip_for_multi_turn():
    """不传 session_id -> 服务端自动建会话并回传 id；回传 id -> 服务端拼历史。"""
    rag = _FakeRAGFlow()
    kb = _kb(rag)
    assert kb.last_session_id == ""
    kb.chat("第一问")
    assert kb.last_session_id == "sess-auto"                      # 响应回传的会话 id
    assert "session_id" not in rag.post_calls[0][1]               # 首问不带
    kb.chat("第二问", session_id=kb.last_session_id)
    assert rag.post_calls[-1][1]["session_id"] == "sess-auto"     # 续问带上


def test_chat_without_session_stays_independent():
    rag = _FakeRAGFlow()
    kb = _kb(rag)
    kb.chat("q1")
    kb.chat("q2")
    assert all("session_id" not in j for _, j in rag.post_calls)  # 默认每次独立会话


# ---------- search_image ----------

def _raw_chunk(content="OCR 文本", doc_type="image", image_id="img-1", sim=0.9, name="规格图.png"):
    """模拟 raw /retrieval 返回的 ES 字段名（doc_type_kwd/docnm_kwd/content_with_weight）。"""
    return {"content_with_weight": content, "doc_type_kwd": doc_type,
            "image_id": image_id, "docnm_kwd": name, "similarity": sim,
            "document_id": "doc-1"}


def test_search_image_filters_to_image_chunks():
    rag = _FakeRAGFlow()
    rag._post_result = {"code": 0, "data": {"chunks": [
        _raw_chunk(content="正文段落", doc_type="text"),                      # 文本块 -> 过滤
        _raw_chunk(image_id="img-a", sim=0.8),
        _raw_chunk(image_id="img-b", sim=0.6),
        _raw_chunk(image_id="", sim=0.7),                                    # 无 image_id -> 跳过
    ]}}
    hits = _kb(rag).search_image("X100 外观", top_k=5)
    assert [h.image_id for h in hits] == ["img-a", "img-b"]
    assert all(h.source == "规格图.png" for h in hits)
    path, payload = rag.post_calls[0]
    assert path == "/retrieval"
    base = get_settings().ragflow_base_url.rstrip("/")
    assert hits[0].url == f"{base}/api/v1/documents/images/img-a"   # image_id 即完整复合 ID
    assert payload["page_size"] == 25
    assert payload["dataset_ids"] == [rag.datasets["biaoshu-products"].id]  # 候选池 x5
    assert payload["include_knowledge_compilation"] is False


def test_search_image_respects_top_k_and_threshold():
    rag = _FakeRAGFlow()
    rag._post_result = {"code": 0, "data": {"chunks": [
        _raw_chunk(image_id=f"img-{i}", sim=0.5) for i in range(10)]}}
    hits = _kb(rag).search_image("q", top_k=2, similarity_threshold=0.4)
    assert [h.image_id for h in hits] == ["img-0", "img-1"]
    assert rag.post_calls[0][1]["similarity_threshold"] == 0.4


def test_search_image_raises_on_error_code():
    rag = _FakeRAGFlow()
    rag._post_result = {"code": 100, "message": "boom", "data": {"chunks": []}}
    with pytest.raises(Exception, match="boom"):
        _kb(rag).search_image("q")


# ---------- attach：连接已存在的 dataset（节点侧语义） ----------

def test_attach_connects_without_creating():
    rag = _FakeRAGFlow()
    ds = rag.create_dataset("biaoshu-run-x")
    kb = KnowledgeBaseV2(dataset_id=ds.id, rag=rag)
    assert kb._dataset is ds
    assert len(rag.datasets) == 1                    # 没有新建
    assert rag.chat_create_calls == []               # 也没有顺手建助手


def test_attach_missing_dataset_points_to_init():
    rag = _FakeRAGFlow()
    with pytest.raises(ValueError, match="biaoshu init"):
        KnowledgeBaseV2(dataset_id="ds-nope", rag=rag)


# ---------- 翻页：远端资源超过一页容量时去重/查找不得漏 ----------

def test_load_dedup_pages_beyond_first_hundred(tmp_path):
    """第 101+ 个远端文档的同名文件必须仍被去重（只翻一页会静默重复上传）。"""
    rag = _FakeRAGFlow()
    kb = _kb(rag)

    old = _FakeDoc(id="doc-old", name="老文件.md")
    rest = [_FakeDoc(id=f"d{i}", name=f"填充{i}.md") for i in range(149)]

    class _PagedDataset:
        def __init__(self, docs):
            self.docs = docs

        def list_documents(self, page=1, page_size=100):
            start = (page - 1) * page_size
            return self.docs[start:start + page_size]

        def upload_documents(self, document_list):
            for ele in document_list:
                assert ele["display_name"] != "老文件.md", "同名老文档被重复上传"
            return [_FakeDoc(id=f"new-{e['display_name']}", name=e["display_name"])
                    for e in document_list]

        def parse_documents(self, ids):
            pass

    kb._dataset = _PagedDataset([old] + rest)
    d = tmp_path / "kb"
    d.mkdir()
    (d / "老文件.md").write_text("x", encoding="utf-8")
    (d / "新文件.md").write_text("x", encoding="utf-8")
    assert kb.load(d) == 1                                     # 只有新文件上传


def test_get_or_create_dataset_pages_beyond_first_hundred():
    """同名 dataset 在第 101+ 位时仍要复用（只翻一页会重复建库）。"""
    rag = _FakeRAGFlow()
    old = rag.create_dataset("biaoshu-products")
    for i in range(120):
        rag.create_dataset(f"占位{i}")
    assert _kb(rag)._dataset is old


# ---------- 回归保护 ----------

def test_kbhit_is_plain_dataclass():
    assert KbHit(text="t", source="s", score=1.0).score == 1.0
