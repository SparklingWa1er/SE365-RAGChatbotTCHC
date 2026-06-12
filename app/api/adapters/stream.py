"""Biến generator Document (channel chat/info/plot) thành SSE event JSON.

Tích luỹ text trả lời + HTML info panel giống vòng trong ChatPage.chat_fn, để mỗi event
gửi đi mang trạng thái ĐẦY ĐỦ hiện tại (frontend render trực tiếp, không cần ghép).
"""
import json
from typing import Iterator

from kotaemon.base import Document


class CitationsPayload:
    """Sentinel mang citation JSON qua stream (Document.channel là Literal cố định nên
    không nhúng được vào Document)."""

    def __init__(self, items: list):
        self.items = items


def sse(event: dict) -> str:
    """Đóng gói một event thành khung SSE trên dây."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def documents_to_events(docs: Iterator) -> Iterator[dict]:
    """Map Document/CitationsPayload -> event dict. KHÔNG gồm event 'done'."""
    text = ""
    info = ""
    for response in docs:
        if isinstance(response, CitationsPayload):
            yield {"type": "citations", "items": response.items}
            continue
        ch = getattr(response, "channel", None)
        if ch is None:
            continue
        if ch == "chat":
            if response.content is None:
                text = ""
                yield {"type": "answer.reset"}
            else:
                text += response.content
                yield {"type": "answer", "text": text}
        elif ch == "info":
            if response.content is None:
                info = ""
            else:
                info += response.content
            yield {"type": "info", "html": info}
        elif ch == "plot":
            yield {"type": "plot", "spec": response.content}


def collect_final(docs: Iterator[Document]) -> tuple[str, str]:
    """(ít dùng) chạy hết generator, trả (text cuối, info html cuối) — cho non-stream."""
    text = ""
    info = ""
    for ev in documents_to_events(docs):
        if ev["type"] == "answer":
            text = ev["text"]
        elif ev["type"] == "answer.reset":
            text = ""
        elif ev["type"] == "info":
            info = ev["html"]
    return text, info
