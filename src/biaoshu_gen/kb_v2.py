"""知识库 v2：ragflow-sdk 薄封装，实际索引、检索和生成由远程 RAGFlow server 运行。

区别于 kb.py 的本地 BM25（POC v1）：v2 面向硬件/服务类标书——标品参数严格，
检索精度要求高，走 RAGFlow 的混合检索与 Agentic RAG（内置 SCA 充分性验证）
生成采购清单等事实依据（设计文档：硬件/服务类标书智能体方案设计）。
"""
from dataclasses import dataclass
from pathlib import Path

import requests
from ragflow_sdk import RAGFlow

from .config import get_settings
import logging

log = logging.getLogger(__name__)

# 允许上传的文件类型（文本口径与 kb.py 一致；docx/pdf/图片交给 RAGFlow 自带解析器）
_UPLOAD_EXTS = {".txt", ".md", ".docx", ".pdf", ".jpg", ".jpeg", ".png", ".pptx"}
# chat 推理模式 -> reasoning 参数值。源码 dialog_service.rag_agent：0/缺省走普通
# async_chat（naive，非 agentic）；1..4 依序映射 THINKING_MODES（low/medium/high/ultra）
# ——low 单次检索无工具环，medium agentic+SCA3 轮，high 加 planner fanout，
# ultra 6 轮 session、SCA5 轮、加 graph_explore。
_THINKING_LEVELS = {"naive": 0, "low": 1, "medium": 2, "high": 3, "ultra": 4}
# search_image 候选扩额：过滤 doc_type=image 后要仍有 top_k 个，召回池按倍数放宽
_IMAGE_CANDIDATE_MULTIPLIER = 5


@dataclass
class KbHit:
    """检索命中：对 ragflow Chunk 的最小映射，不向调用方泄漏 SDK 类型。"""

    text: str
    source: str    # 来源文档名
    score: float   # 混合相似度（向量 + 关键词加权）


@dataclass
class KbImageHit:
    """图片检索命中（doc_type=image 的块，OCR 文本参与召回）。

    url 指向 RAGFlow 图片端点 /api/v1/documents/images/{dataset_id}-{image_id}，
    需带 Bearer 鉴权头；字节经 kb.get_image_bytes() 拉取，前端直出可自行挂鉴权。
    """

    text: str           # OCR 文本（召回依据）
    source: str         # 来源文档名
    score: float        # 混合相似度
    image_id: str
    url: str


def _source_name(chunk: dict) -> str:
    """来源文档名：ES 字段是 docnm_kwd/document_keyword，SDK 风格是 document_name。"""
    return (chunk.get("docnm_kwd") or chunk.get("document_keyword")
            or chunk.get("document_name") or "")


def _paged(fetch_page, page_size: int = 100) -> list:
    """翻页收集 SDK 列表方法的全部结果（服务端 page_size 上限 100）。

    只取一页的话，第 101 个之后的远端资源会被漏掉——load 的同名去重、
    dataset/助手 get-or-create 都会因此静默重复，必须翻到取完为止。
    """
    out: list = []
    page = 1
    while True:
        batch = fetch_page(page, page_size)
        out.extend(batch)
        if len(batch) < page_size:
            return out
        page += 1


def search_snippets(state, query: str, top_k: int | None = None) -> list[tuple[str, str]]:
    """节点统一检索入口：产品知识库（kb_v2）混合检索，只检索、不生成。

    企业信息不走检索（ledger 记账，见 ledger.py）。run 未启用 RAGFlow
    （init 用了 --skip-ragflow）时直接报错指向重跑 init。
    返回 [(来源文档名, 文本)]。
    """
    log.info("[kb] 检索: %s", query)
    dataset_id = getattr(state, "ragflow_dataset_id", "")
    if not dataset_id:
        raise ValueError(
            "该 run 未启用 RAGFlow 知识库（run.json 无 ragflow_dataset_id）。"
            "产品资料检索依赖它，请重跑 biaoshu init（不要加 --skip-ragflow）。")
    hits = KnowledgeBaseV2.attach(dataset_id).search(query, top_k=top_k)
    return [(h.source, h.text) for h in hits]


class KnowledgeBaseV2:
    """load 上传目录、search 纯检索、chat 走 Agentic RAG，三方法语义见各 docstring。

    dataset/chat 助手均 get-or-create：同名复用远端已有资源，可重复构造不重复建。
    """

    def __init__(
        self,
        dataset_name: str | None = None,
        *,
        dataset_id: str | None = None,
        rag: RAGFlow | None = None,
        think: str = "medium",
    ):
        """两种构造语义：
        - dataset_name：init 流程用——get-or-create，不存在则创建；
        - dataset_id：节点/后续命令用——只连接已存在的库，不存在报错指向重跑
          init（静默重建会得到空库，检索永远落空，比报错危险）。
        两者都缺省时退回配置的固定产品库（RAGFLOW_DATASET_NAME）。think 是默认
        推理模式，chat 可按次覆盖。
        """
        settings = get_settings()
        self._rag = rag or RAGFlow(
            api_key=settings.ragflow_api_key, base_url=settings.ragflow_base_url,
        )
        if dataset_id:
            found = [d for d in _paged(self._rag.list_datasets) if d.id == dataset_id]
            if not found:
                raise ValueError(
                    f"RAGFlow dataset {dataset_id} 不存在（可能被手动删除）。"
                    "请重跑 biaoshu init 重建该 run 的知识库。")
            self._dataset = found[0]
        else:
            self._dataset = self._get_or_create_dataset(
                dataset_name or settings.ragflow_dataset_name)
        self._chat_assistant = None
        self._think = think
        self.last_session_id = ""   # 最近一次 chat 的会话 id（多轮追问时回传）

    @classmethod
    def attach(cls, dataset_id: str, *, rag: RAGFlow | None = None,
               think: str = "medium") -> "KnowledgeBaseV2":
        """节点/后续命令的连接入口：只连接 init 已建的 dataset，不创建不上传。"""
        return cls(dataset_id=dataset_id, rag=rag, think=think)

    # ---------- load ----------

    def load(self, source: Path | list[Path], *, wait: bool = True) -> int:
        """上传进本知识库并触发解析；同名文件跳过。返回新上传文件数。

        source 传目录（递归收白名单文件）或显式文件清单（init 按记账分流后的
        产品资料清单）。wait=True（默认）阻塞至新文档全部解析到终态，返回后
        即可 search/chat；wait=False 只提交解析任务立即返回。
        """
        if isinstance(source, list):
            candidates = sorted(
                p for p in source
                if p.is_file() and not p.name.startswith(".")
                and p.suffix.lower() in _UPLOAD_EXTS
            )
        else:
            source = Path(source)
            if not source.exists():
                return 0
            candidates = sorted(
                p for p in source.rglob("*")
                if p.is_file() and not p.name.startswith(".")
                and p.suffix.lower() in _UPLOAD_EXTS
            )
        existing = {d.name for d in _paged(
            lambda page, ps: self._dataset.list_documents(page=page, page_size=ps))}
        todo = [p for p in candidates if p.name not in existing]
        docs: list = []
        for p in todo:
            docs.extend(self._dataset.upload_documents(
                [{"display_name": p.name, "blob": p.read_bytes()}],
            ))
        if not docs:
            return 0
        ids = [d.id for d in docs]
        if wait:
            self._dataset.parse_documents(ids)          # SDK 内部轮询至 DONE/FAIL/CANCEL
        else:
            self._dataset.async_parse_documents(ids)
        return len(docs)

    # ---------- search ----------

    def search(
        self,
        query: str,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        vector_similarity_weight: float | None = None,
    ) -> list[KbHit]:
        """混合检索（全文关键词 + 向量加权融合），只检索、不生成。

        走 raw /retrieval 并带 include_knowledge_compilation=false：RAPTOR 树等
        知识编译产物（content 为 {"name":...} JSON 的 entity/relation 块）默认会
        占满召回（实测 top-10 全是），须在服务端排除；SDK retrieve() 不透传该参数。
        vector_similarity_weight 越小关键词占比越高；SDK 默认 0.3，硬件参数类
        查询建议维持默认或调低，靠术语匹配保参数精度。
        """
        extra: dict = {}
        if similarity_threshold is not None:
            extra["similarity_threshold"] = similarity_threshold
        if vector_similarity_weight is not None:
            extra["vector_similarity_weight"] = vector_similarity_weight
        chunks = self._retrieve_raw(query, page_size=top_k or get_settings().kb_top_k, **extra)
        return [
            KbHit(
                text=c.get("content") or c.get("content_with_weight") or "",
                source=_source_name(c),
                score=float(c.get("similarity") or 0.0),
            )
            for c in chunks
        ]

    # ---------- search_image ----------

    def search_image(
        self,
        query: str,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
    ) -> list[KbImageHit]:
        """图片检索：混合检索召回（图片块以 OCR 文本参与），后过滤 doc_type=image。

        候选池按倍数放宽，保证过滤后仍有约 top_k 个图片命中。
        """
        top_k = top_k or get_settings().kb_top_k
        extra: dict = {}
        if similarity_threshold is not None:
            extra["similarity_threshold"] = similarity_threshold
        chunks = self._retrieve_raw(
            query, page_size=min(top_k * _IMAGE_CANDIDATE_MULTIPLIER, 100), **extra)

        settings = get_settings()
        base = settings.ragflow_base_url.rstrip("/")
        hits: list[KbImageHit] = []
        for c in chunks:
            if (c.get("doc_type_kwd") or c.get("doc_type")) != "image":
                continue
            image_id = c.get("image_id") or ""
            if not image_id:
                continue
            hits.append(KbImageHit(
                text=c.get("content_with_weight") or c.get("content") or "",
                source=_source_name(c),
                score=float(c.get("similarity") or 0.0),
                image_id=image_id,
                # 实测 image_id 已是完整复合 ID（{dataset_id}-{对象键}），端点按首个
                # 连字符切出 bucket/对象名，不能再拼一次 dataset 前缀
                url=f"{base}/api/v1/documents/images/{image_id}",
            ))
            if len(hits) >= top_k:
                break
        return hits

    def _retrieve_raw(self, query: str, page_size: int, **params) -> list[dict]:
        """raw /retrieval：返回原始 chunk 字典列表。

        不走 SDK retrieve()：SDK 的 Chunk 会丢弃 image_id/doc_type_kwd 等未知字段，
        且不透传 include_knowledge_compilation。衍生块在服务端用 must_not 排除
        （compile_kwd 存在即排除，见 RAGFlow chunk_api.py）。
        """
        payload: dict = {
            "dataset_ids": [self._dataset.id],
            "question": query,
            "page": 1,
            "page_size": page_size,
            "knn_top_k": 1024,
            "include_knowledge_compilation": False,
            **params,
        }
        res = self._rag.post("/retrieval", json=payload).json()
        if res.get("code") != 0:
            raise Exception(res.get("message"))
        return res["data"].get("chunks", [])

    def get_image_bytes(self, hit: KbImageHit) -> bytes:
        """带 Bearer 鉴权拉取图片字节（PNG/JPEG 原样返回）。"""
        settings = get_settings()
        resp = requests.get(
            hit.url,
            headers={"Authorization": f"Bearer {settings.ragflow_api_key}"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.content

    # ---------- chat ----------

    def chat(self, question: str, think: str | None = None,
             session_id: str | None = None, **extra) -> str:
        """Agentic RAG 问答：RAGFlow 内部多轮检索 + SCA 充分性验证后生成回答。

        走 POST /chat/completions（/chats/{id}/completions 已废弃）。
        会话与历史：不传 session_id 时服务端每次新建会话，模型只看本次问题
        （标书节点用，无串扰）；要多轮追问就把上次响应记录的 last_session_id
        传回来，服务端会把该会话的历史拼进上下文。
        前提：dataset 内已有解析完成的文件（空库建助手会被 server 拒绝）。
        think 按次覆盖默认推理模式：naive 纯检索直答；low 单次检索；
        medium 起 agentic+SCA；high/ultra 逐级加深（见 _THINKING_LEVELS 注释）。
        设计文档用法：对采购清单用内置 chat 出采购建议，作为技术方案编写的事实
        依据。额外键值对原样透传补全端点（调试服务端参数用），显式传 reasoning
        时以调用方为准。
        """
        level = _THINKING_LEVELS.get(think or self._think)
        if level is None:
            raise ValueError(f"think 须为 {sorted(_THINKING_LEVELS)} 之一，收到 {think!r}")
        payload = {
            "chat_id": self._get_chat_assistant().id,
            "question": question,
            "stream": False,
            "reasoning": level,
            **extra,
        }
        if session_id:
            payload["session_id"] = session_id
        res = self._rag.post("/chat/completions", json=payload).json()
        if res.get("code") != 0:
            raise Exception(res.get("message"))
        data = res.get("data") or {}
        self.last_session_id = data.get("session_id") or session_id or ""
        return data.get("answer") or ""

    # ---------- 远端资源 get-or-create ----------

    def _get_or_create_dataset(self, name: str):
        """按名 get-or-create。不走 SDK 的 name 过滤：部分 server 版本对不存在的名字
        不返回空列表而是抛权限错误（实测），故全量翻页后本地匹配。"""
        found = [d for d in _paged(self._rag.list_datasets) if d.name == name]
        if found:
            return found[0]
        return self._rag.create_dataset(name)

    def _get_chat_assistant(self):
        """按名 get-or-create 助手（实例内缓存）。不走 SDK 的 name 过滤：部分
        server 版本对不存在的名字不返回空列表而是抛权限错误（实测），故全量
        翻页后本地匹配。"""
        if self._chat_assistant is not None:
            return self._chat_assistant
        settings = get_settings()
        found = [c for c in _paged(self._rag.list_chats)
                 if c.name == settings.ragflow_chat_name]
        if found:
            chat = found[0]
            if list(chat.dataset_ids or []) != [self._dataset.id]:
                # 残留助手可能绑着别的库（实测踩过：绑到手动实验的库导致检索永远
                # 落空）：本类契约是助手绑当前 dataset，发现错绑就改绑
                chat.update({"dataset_ids": [self._dataset.id]})
                chat.dataset_ids = [self._dataset.id]
            self._chat_assistant = chat
            return chat
        self._chat_assistant = self._rag.create_chat(
            name=settings.ragflow_chat_name, dataset_ids=[self._dataset.id],
            llm_id=settings.ragflow_llm_id or None,   # 空则用租户默认模型
        )
        return self._chat_assistant
