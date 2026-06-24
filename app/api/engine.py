"""Engine: dựng pipeline + chạy stream — port gọn từ ChatPage.create_pipeline/chat_fn.

KHÔNG phụ thuộc Gradio. Trả về generator các dict event (xem adapters/stream.py để
chuyển sang SSE).
"""
import html as _html
from copy import deepcopy
from typing import Iterator, Optional

from kotaemon.base import Document

from .context import DEFAULT_USER_ID, default_settings_dict, get_context

DEFAULT_SETTING = "(default)"


def _esc(s: str) -> str:
    """Escape ký tự HTML nguy hiểm (& < >) nhưng GIỮ \\n và cú pháp markdown (| bảng,
    -, *). Frontend chạy marked để dựng bảng/list/đậm (xem markdown.ts) — bám cách
    Gradio render markdown answer/evidence."""
    return _html.escape(s or "", quote=False)


def _highlight_doc(text: str, ss: list) -> str:
    """Toàn văn `text` với các span tô sáng (<mark>) + chèn 【idx】 inline.

    Bám sát thuật toán prepare_citations (citation_qa.py) nhưng escape an toàn cho HTML.
    """
    if not ss:
        return _esc(text)
    ss = sorted(ss, key=lambda x: x["start"])
    out = [_esc(text[: ss[0]["start"]])]
    last_end = 0
    for i, span in enumerate(ss):
        span_start = max(last_end, span["start"])
        span_end = max(last_end, span["end"])
        last_end = span_end
        idx = span.get("idx")
        marker = f"【{idx}】" if idx is not None else ""
        out.append(f"<mark>{marker}{_esc(text[span_start:span_end])}</mark>")
        if i < len(ss) - 1:
            out.append(_esc(text[span["end"] : ss[i + 1]["start"]]))
    out.append(_esc(text[ss[-1]["end"]:]))
    return "".join(out)


def build_settings(overrides: Optional[dict] = None) -> dict:
    """Lấy default settings phẳng rồi áp override per-request.

    overrides (tất cả optional): reasoning_type, llm, language, use_mindmap, use_citation.
    """
    from . import store

    settings = deepcopy(default_settings_dict())
    settings.update(store.get_user_setting())  # override đã lưu của user (nền)
    overrides = overrides or {}

    reasoning_type = overrides.get("reasoning_type")
    if reasoning_type and reasoning_type != DEFAULT_SETTING:
        settings["reasoning.use"] = reasoning_type

    language = overrides.get("language")
    if language and language != DEFAULT_SETTING:
        settings["reasoning.lang"] = language

    # mindmap/citation áp cho cả simple lẫn ReAct (key theo từng engine)
    use_mindmap = overrides.get("use_mindmap")
    use_citation = overrides.get("use_citation")
    llm = overrides.get("llm")
    for rid in ("simple", "ReAct"):
        if use_mindmap is not None:
            k = f"reasoning.options.{rid}.create_mindmap"
            if k in settings:
                settings[k] = use_mindmap
        if use_citation is not None:
            k = f"reasoning.options.{rid}.highlight_citation"
            if k in settings:
                settings[k] = use_citation
        if llm and llm != DEFAULT_SETTING:
            k = f"reasoning.options.{rid}.llm"
            if k in settings:
                settings[k] = llm

    return settings


def _all_source_ids(index, user_id: str) -> list[str]:
    """Toàn bộ file id của index (mode 'search all'). Port get_selected_ids('all').

    Retriever bỏ qua retrieval khi doc_ids rỗng (pipelines.py:142), nên search-all
    PHẢI truyền đủ id. Lọc theo user chỉ khi index private=true (mặc định false — LỖI #4).
    """
    from sqlmodel import Session, select

    from ktem.db.models import engine as db_engine

    Source = index._resources["Source"]
    with Session(db_engine) as s:
        stmt = select(Source.id)
        if index.config.get("private", False):
            stmt = stmt.where(Source.user == user_id)
        return [row[0] if isinstance(row, tuple) else row for row in s.exec(stmt).all()]


def _retrievers_for_index(index, settings: dict, user_id: str,
                          selected_ids: Optional[list[str]]) -> list:
    """Port ktem index.get_retriever_pipelines NHƯNG tự cấp selected_ids (headless:
    _selector_ui = None vì ta không dựng UI)."""
    prefix = f"index.options.{index.id}."
    stripped = {k[len(prefix):]: v for k, v in settings.items() if k.startswith(prefix)}

    retrievers = []
    for cls in index._retriever_pipeline_cls:
        obj = cls.get_pipeline(stripped, index.config, selected_ids)
        if obj is None:
            continue
        obj.Source = index._resources["Source"]
        obj.Index = index._resources["Index"]
        obj.VS = index._vs
        obj.DS = index._docstore
        obj.FSPath = index._fs_path
        obj.user_id = user_id
        retrievers.append(obj)
    return retrievers


def _build_retrievers(settings: dict, selected_file_ids: Optional[list[str]],
                      user_id: str) -> list:
    """Dựng retriever cho mọi index. selected_file_ids rỗng => search all."""
    ctx = get_context()
    retrievers: list = []
    for index in ctx.index_manager.indices:
        selected_ids = selected_file_ids or _all_source_ids(index, user_id)
        retrievers += _retrievers_for_index(index, settings, user_id, selected_ids)
    return retrievers


def create_pipeline(settings: dict, selected_file_ids: Optional[list[str]],
                    user_id: str = DEFAULT_USER_ID, regen: bool = False):
    """Dựng reasoning pipeline từ settings (port từ ChatPage.create_pipeline)."""
    from ktem.components import reasonings

    reasoning_mode = settings["reasoning.use"]
    reasoning_cls = reasonings[reasoning_mode]
    reasoning_id = reasoning_cls.get_info()["id"]

    retrievers = _build_retrievers(settings, selected_file_ids, user_id)

    state = {"app": {"regen": regen}, "pipeline": {}}
    pipeline = reasoning_cls.get_pipeline(settings, state, retrievers)
    return pipeline, reasoning_id


def build_citations(pipeline, answer) -> Optional[list[dict]]:
    """Bóc tách citation thành JSON từ answer + nguồn đã gom — KHÔNG đụng backend.

    Tái dùng pipeline.answering_pipeline.match_evidence_with_context (đã trả spans có
    {start,end,idx}) + collected_docs (đã áp friendly names trong react.stream).
    Trả None nếu không có citation.
    """
    if answer is None:
        return None
    meta = getattr(answer, "metadata", None) or {}
    if not meta.get("citation"):
        return None
    # Lấy tập tài liệu đã dùng để dựng câu trả lời:
    #  - ReAct (react.py): gom nhiều bước -> _dedup_collected()
    #  - Trả lời nhanh (simple.py FullQAPipeline): không có _dedup_collected, dùng
    #    _last_docs (tài liệu đã rerank/lọc, do stream() lưu lại).
    if hasattr(pipeline, "_dedup_collected"):
        docs = pipeline._dedup_collected()
    else:
        docs = getattr(pipeline, "_last_docs", None) or []
    if not docs:
        return None
    try:
        spans = pipeline.answering_pipeline.match_evidence_with_context(answer, docs)
    except Exception:
        return None

    id2doc = {getattr(d, "doc_id", None): d for d in docs}
    cited: list[dict] = []
    cited_ids: set = set()
    for doc_id, ss in spans.items():
        doc = id2doc.get(doc_id)
        if doc is None or not ss:
            continue
        cited_ids.add(doc_id)
        ordered = sorted(ss, key=lambda x: x["start"])
        idxs = sorted({s["idx"] for s in ss if s.get("idx") is not None})
        snippet = " … ".join((doc.text or "")[s["start"]:s["end"]] for s in ordered)
        m = doc.metadata or {}
        cited.append({
            "indices": idxs,
            "title": m.get("file_name", "-"),
            "snippet": snippet[:500],
            "content_html": _highlight_doc(doc.text or "", ss),  # toàn văn + highlight + 【n】
            "score": m.get("llm_trulens_score"),
            "is_web": bool(m.get("is_web")),
            "url": m.get("web_url"),
            "cited": True,  # 📌 được trích dẫn (có 【n】)
        })
    cited.sort(key=lambda c: c["indices"][0] if c["indices"] else 10**9)

    # 📚 Nguồn tham khảo: tài liệu đã gom nhưng câu trả lời KHÔNG trích trực tiếp
    # (không khớp span nào). Xếp theo độ liên quan giảm dần.
    others: list[dict] = []
    for doc in docs:
        if getattr(doc, "doc_id", None) in cited_ids:
            continue
        m = doc.metadata or {}
        others.append({
            "indices": [],
            "title": m.get("file_name", "-"),
            "snippet": (doc.text or "")[:500],
            "content_html": _esc(doc.text or ""),  # toàn văn thuần (không có 【n】)
            "score": m.get("llm_trulens_score"),
            "is_web": bool(m.get("is_web")),
            "url": m.get("web_url"),
            "cited": False,  # 📚 tham khảo (không trích dẫn trực tiếp)
        })
    others.sort(key=lambda c: c["score"] if c["score"] is not None else -1.0, reverse=True)

    return cited + others


def stream_chat(
    message: str,
    conversation_id: str,
    history: list[tuple[str, str]],
    settings_override: Optional[dict] = None,
    selected_file_ids: Optional[list[str]] = None,
    user_id: str = DEFAULT_USER_ID,
    regen: bool = False,
) -> Iterator[Document]:
    """Generator yield Document (channel chat/info/plot) — giống vòng trong chat_fn.

    Sau khi stream xong, phát thêm Document(channel="citations_json") chứa citation
    có cấu trúc (xem build_citations + adapter).

    history: list [(user, bot), ...] (đã loại tin đang hỏi).
    """
    settings = build_settings(settings_override)
    pipeline, _ = create_pipeline(settings, selected_file_ids, user_id, regen)

    # yield from truyền lại return value của generator (react.stream return answer)
    answer = yield from pipeline.stream(message, conversation_id, history)

    # Dựng citation KHÔNG được phép làm chết stream: nếu lỗi (vd engine không có
    # _dedup_collected) thì bỏ qua phần nguồn, vẫn để _run_stream gửi event "done".
    try:
        cites = build_citations(pipeline, answer)
    except Exception:
        import traceback
        traceback.print_exc()
        cites = None
    if cites:
        from .adapters.stream import CitationsPayload
        yield CitationsPayload(cites)
