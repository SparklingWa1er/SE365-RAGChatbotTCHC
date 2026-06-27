"""Memory cho agent ReAct — component dự án (không thuộc kotaemon gốc).

Hai lớp bộ nhớ, đóng khung theo mô hình MemGPT (arXiv 2310.08560 — bộ nhớ phân tầng
kiểu hệ điều hành):

  Lớp A · Summary-Buffer (ngắn hạn / "recall")
      Giữ N lượt gần nhất nguyên văn + TÓM TẮT bằng LLM các lượt cũ hơn thành một
      đoạn. Thay cho việc cắt cứng lịch sử → giữ ngữ cảnh dài mà không phình token.
      Tham khảo: LangChain ConversationSummaryBufferMemory.

  Lớp B · Episodic/Semantic (dài hạn / "archival")
      Lưu mỗi lượt (câu hỏi đã chuẩn hoá + trả lời) và các "fact" bền vững về người
      dùng vào MỘT collection Chroma riêng (tách khỏi corpus thủ tục), khoá theo
      user_id. Trước khi agent gom nguồn, RECALL top-k ký ức liên quan để cá nhân hoá
      và nối mạch xuyên hội thoại. Tham khảo: Memory Construction & Retrieval for
      Conversational Agents (arXiv 2502.05589); cách phân tầng của mem0.

Cả hai lớp BẬT/TẮT độc lập qua biến môi trường để dễ ABLATION (xem from_env):
    MEM_SUMMARY=1|0   — Lớp A (mặc định 1)
    MEM_EPISODIC=1|0  — Lớp B store+recall (mặc định 1)
    MEM_FACTS=1|0     — trích fact ngữ nghĩa cho Lớp B (mặc định 0 — tốn 1 lời gọi
                        LLM/lượt; episodic Q&A vẫn chạy khi tắt)

Module này CHỈ import nặng (chromadb) khi thực sự dùng Lớp B (lazy) để an toàn khi
import sớm. Mọi lỗi của memory được nuốt ở tầng gọi (react.stream) — memory KHÔNG
bao giờ được làm chết một câu trả lời.
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from kotaemon.base import HumanMessage, SystemMessage
from kotaemon.llms import PromptTemplate

from rag.prompts import MEMORY_FACT_PROMPT, MEMORY_SUMMARY_PROMPT

logger = logging.getLogger(__name__)

# Tên collection Chroma cho ký ức hội thoại (tách hẳn khỏi index corpus index_1).
MEMORY_COLLECTION = "agent_memory"


def _truthy(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _memory_persist_dir() -> str:
    """Thư mục lưu Chroma memory — bám KH_APP_DATA_DIR (PHẢI ASCII trên Windows,
    xem LỖI #2: hnswlib không tạo được .bin nếu path có Unicode)."""
    base = os.environ.get("KH_APP_DATA_DIR", r"C:\ktem_data")
    path = Path(base) / "user_data" / MEMORY_COLLECTION
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _embed_one(embedding, text: str) -> list[float]:
    """Embed một chuỗi → vector. embedding(text) trả list[DocumentWithEmbedding]."""
    out = embedding(text)
    first = out[0] if isinstance(out, list) else out
    return list(getattr(first, "embedding", first))


# ───────────────────────────── Lớp B: Episodic store ────────────────────────
class EpisodicMemory:
    """Kho ký ức dài hạn trên Chroma. add() ghi một ký ức, recall() truy hồi top-k
    theo độ tương đồng (cosine), lọc theo user_id."""

    def __init__(self, embedding, persist_dir: Optional[str] = None):
        import chromadb  # lazy — chỉ nạp khi Lớp B bật

        self.embedding = embedding
        client = chromadb.PersistentClient(path=persist_dir or _memory_persist_dir())
        # cosine để score = 1 - distance nằm trong [0,1], dễ đặt ngưỡng.
        self.col = client.get_or_create_collection(
            MEMORY_COLLECTION, metadata={"hnsw:space": "cosine"}
        )

    def add(self, user_id: str, conv_id: str, text: str, kind: str = "episode") -> None:
        text = (text or "").strip()
        if not text:
            return
        self.col.add(
            ids=[uuid.uuid4().hex],
            embeddings=[_embed_one(self.embedding, text)],
            documents=[text],
            metadatas=[{"user_id": user_id or "default",
                        "conv_id": conv_id or "", "kind": kind}],
        )

    def recall(self, user_id: str, query: str, k: int = 3,
               min_score: float = 0.25, exclude_conv: Optional[str] = None) -> list[str]:
        """Trả tối đa k đoạn ký ức liên quan (đã lọc theo ngưỡng tương đồng).

        exclude_conv: bỏ qua ký ức của CHÍNH hội thoại hiện tại (đã nằm trong history,
        khỏi nhắc lại). Lọc theo user_id để không lẫn ký ức người khác.
        """
        query = (query or "").strip()
        total = self.col.count()
        if not query or total == 0:
            return []
        try:
            res = self.col.query(
                query_embeddings=[_embed_one(self.embedding, query)],
                # lấy dư rồi lọc ngưỡng/exclude; cap theo tổng phần tử để chroma khỏi cảnh báo.
                n_results=min(max(k * 2, k), total),
                where={"user_id": user_id or "default"},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("EpisodicMemory.recall lỗi: %s", e)
            return []

        docs = (res.get("documents") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        out: list[str] = []
        for doc, dist, meta in zip(docs, dists, metas):
            score = 1.0 - float(dist)  # cosine distance → similarity
            if score < min_score:
                continue
            if exclude_conv and (meta or {}).get("conv_id") == exclude_conv:
                continue
            out.append(doc)
            if len(out) >= k:
                break
        return out


# ─────────────────────────────── Facade ─────────────────────────────────────
class MemoryManager:
    """Gộp Lớp A + Lớp B sau một giao diện. react.stream gọi 3 hàm:
        summarize(history)               -> str   (Lớp A)
        recall(user_id, query, conv_id)  -> list  (Lớp B đọc)
        observe(user_id, conv_id, q, a)  -> None  (Lớp B ghi)
    và build_extra_context() để ghép thành khối ngữ cảnh tiêm vào contextualize.
    """

    def __init__(self, llm, lang: str = "Vietnamese", *, episodic: Optional[EpisodicMemory] = None,
                 enable_summary: bool = True, enable_facts: bool = False,
                 keep_recent: int = 3, recall_k: int = 3):
        self.llm = llm
        self.lang = lang
        self.episodic = episodic            # None = tắt Lớp B
        self.enable_summary = enable_summary
        self.enable_facts = enable_facts
        self.keep_recent = keep_recent
        self.recall_k = recall_k

    # -- factory đọc cờ môi trường (cho cả app lẫn ablation) -------------------
    @classmethod
    def from_env(cls, llm, lang: str = "Vietnamese", embedding=None,
                 persist_dir: Optional[str] = None,
                 keep_recent: int = 3, recall_k: int = 3) -> "MemoryManager":
        episodic = None
        if _truthy("MEM_EPISODIC") and embedding is not None:
            try:
                episodic = EpisodicMemory(embedding, persist_dir)
            except Exception as e:  # noqa: BLE001 — thiếu chromadb/ổ đĩa → tắt Lớp B
                logger.warning("Không khởi tạo được EpisodicMemory: %s", e)
        return cls(
            llm, lang, episodic=episodic,
            enable_summary=_truthy("MEM_SUMMARY"),
            enable_facts=_truthy("MEM_FACTS", default="0"),
            keep_recent=keep_recent, recall_k=recall_k,
        )

    @property
    def active(self) -> bool:
        return self.enable_summary or self.episodic is not None

    # -- Lớp A ----------------------------------------------------------------
    def summarize(self, history: list) -> str:
        """Tóm tắt các lượt CŨ (ngoài keep_recent lượt gần nhất). '' nếu không cần
        (lịch sử còn ngắn) hoặc Lớp A tắt."""
        if not self.enable_summary or not history:
            return ""
        if len(history) <= self.keep_recent:
            return ""
        old = history[: -self.keep_recent]
        chat = "\n".join(f"Người dùng: {h}\nTrợ lý: {a}" for h, a in old)
        prompt = PromptTemplate(MEMORY_SUMMARY_PROMPT).populate(
            chat_history=chat, lang=self.lang
        )
        try:
            resp = self.llm(
                [SystemMessage(content="Bạn là trợ lý tóm tắt hội thoại."),
                 HumanMessage(content=prompt)]
            )
            return (resp.text or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("MemoryManager.summarize lỗi: %s", e)
            return ""

    # -- Lớp B đọc ------------------------------------------------------------
    def recall(self, user_id: str, query: str, conv_id: Optional[str] = None) -> list[str]:
        if self.episodic is None:
            return []
        return self.episodic.recall(
            user_id, query, k=self.recall_k, exclude_conv=conv_id
        )

    # -- Lớp B ghi ------------------------------------------------------------
    def observe(self, user_id: str, conv_id: str, question: str, answer: str) -> None:
        """Ghi lượt vừa xong vào ký ức dài hạn: một episode (Q→A rút gọn) + (tuỳ chọn)
        các fact ngữ nghĩa."""
        if self.episodic is None:
            return
        q = (question or "").strip()
        a = (answer or "").strip()
        if not q:
            return
        episode = f"Người dùng từng hỏi: {q}\nĐáp: {a[:400]}"
        try:
            self.episodic.add(user_id, conv_id, episode, kind="episode")
        except Exception as e:  # noqa: BLE001
            logger.warning("observe(episode) lỗi: %s", e)

        if self.enable_facts:
            for fact in self._extract_facts(q, a):
                try:
                    self.episodic.add(user_id, conv_id, fact, kind="fact")
                except Exception as e:  # noqa: BLE001
                    logger.warning("observe(fact) lỗi: %s", e)

    def _extract_facts(self, question: str, answer: str) -> list[str]:
        prompt = PromptTemplate(MEMORY_FACT_PROMPT).populate(
            question=question, answer=answer
        )
        try:
            resp = self.llm(
                [SystemMessage(content="Bạn rút trích thông tin đáng nhớ về người dùng."),
                 HumanMessage(content=prompt)]
            )
            text = (resp.text or "").strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("_extract_facts lỗi: %s", e)
            return []
        if not text or text.strip().upper().startswith("KHÔNG"):
            return []
        facts = []
        for ln in text.splitlines():
            ln = ln.strip(" -•\t").strip()
            if len(ln) >= 4:
                facts.append(ln)
        return facts[:5]

    # -- ghép khối ngữ cảnh tiêm vào contextualize ----------------------------
    @staticmethod
    def build_extra_context(summary: str, recalled: list[str]) -> str:
        parts = []
        if summary:
            parts.append(f"[TÓM TẮT CÁC LƯỢT TRƯỚC]\n{summary}")
        if recalled:
            parts.append("[GHI NHỚ DÀI HẠN VỀ NGƯỜI DÙNG]\n" + "\n".join(f"- {r}" for r in recalled))
        return "\n\n".join(parts)
