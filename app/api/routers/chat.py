"""Chat: stream SSE + regen + stop.

POST /api/chat            — gửi tin mới (tạo hội thoại nếu cần)
POST /api/chat/{id}/regen — trả lời lại lượt cuối
POST /api/chat/stop       — yêu cầu dừng stream của một hội thoại (cooperative)
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import store
from ..adapters.stream import documents_to_events, sse
from ..context import DEFAULT_USER_ID
from ..engine import stream_chat
from ..schemas import ChatRequest
from .suggestions import generate_suggestions

router = APIRouter(prefix="/api", tags=["chat"])

# Hội thoại đang được yêu cầu dừng (cooperative cancel: kiểm tra giữa các event).
_cancelled: set[str] = set()


class StopRequest(BaseModel):
    conversation_id: str


def _run_stream(conv_id: str, message: str, history: list, overrides: dict | None,
                selected_file_ids: list[str], regen: bool):
    """Generator các khung SSE cho một lượt chat. Lưu lượt + sinh gợi ý ở cuối."""
    lang = (overrides or {}).get("language")
    last_text, last_info = "", ""
    cancelled = False

    docs = stream_chat(
        message=message,
        conversation_id=conv_id,
        history=history,
        settings_override=overrides,
        selected_file_ids=selected_file_ids,
        regen=regen,
    )
    for ev in documents_to_events(docs):
        if conv_id in _cancelled:
            cancelled = True
            break
        if ev["type"] == "answer":
            last_text = ev["text"]
        elif ev["type"] == "answer.reset":
            last_text = ""
        elif ev["type"] == "info":
            last_info = ev["html"]
        yield sse(ev)

    _cancelled.discard(conv_id)

    if cancelled:
        if last_text:
            store.append_message(conv_id, message, last_text, last_info)
        yield sse({"type": "done", "conversation_id": conv_id,
                   "cancelled": True, "suggestions": []})
        return

    if last_text:
        store.append_message(conv_id, message, last_text, last_info)
    new_history = history + [(message, last_text)]
    try:
        suggestions = generate_suggestions(new_history, lang)
        store.save_suggestions(conv_id, suggestions)
    except Exception:
        suggestions = []
    yield sse({"type": "done", "conversation_id": conv_id,
               "suggestions": suggestions})


@router.post("/chat")
def chat(req: ChatRequest):
    conv_id = req.conversation_id or store.create_conversation(
        user_id=DEFAULT_USER_ID)["id"]
    detail = store.get_conversation(conv_id) or {}
    history = [tuple(m) for m in detail.get("messages", [])]
    overrides = req.settings_override.model_dump() if req.settings_override else None

    return StreamingResponse(
        _run_stream(conv_id, req.message, history, overrides,
                    req.selected_file_ids, req.regen),
        media_type="text/event-stream",
        headers={"X-Conversation-Id": conv_id, "Cache-Control": "no-cache"},
    )


@router.post("/chat/{conv_id}/regen")
def regen(conv_id: str):
    detail = store.get_conversation(conv_id)
    if detail is None:
        raise HTTPException(404, "Conversation not found")
    msgs = detail.get("messages", [])
    if not msgs:
        raise HTTPException(400, "No message to regenerate")
    last_user = msgs[-1][0]
    store.drop_last_message(conv_id)
    history = [tuple(m) for m in msgs[:-1]]

    return StreamingResponse(
        _run_stream(conv_id, last_user, history, None, [], regen=True),
        media_type="text/event-stream",
        headers={"X-Conversation-Id": conv_id, "Cache-Control": "no-cache"},
    )


@router.post("/chat/stop")
def stop(req: StopRequest):
    _cancelled.add(req.conversation_id)
    return {"ok": True, "conversation_id": req.conversation_id}
