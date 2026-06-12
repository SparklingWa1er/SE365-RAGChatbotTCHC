"""Gợi ý câu hỏi — tái dùng SuggestFollowupQuesPipeline + câu mẫu mặc định."""
import json
import re
from typing import Optional

from fastapi import APIRouter, HTTPException

from .. import store
from ..schemas import SuggestRequest

router = APIRouter(prefix="/api", tags=["suggestions"])


def default_samples() -> list[list[str]]:
    from ktem.pages.chat.chat_suggestion import ChatSuggestion
    return [[s] for s in ChatSuggestion.CHAT_SAMPLES]


def generate_suggestions(chat_history: list, lang: Optional[str] = None
                         ) -> list[list[str]]:
    """Sinh 3-5 follow-up từ lịch sử; rỗng/lỗi -> câu mẫu mặc định.

    chat_history: list (user, bot). Logic port từ ChatPage.suggest_chat_conv.
    """
    from ktem.pages.chat import SUPPORTED_LANGUAGE_MAP
    from ktem.reasoning.prompt_optimization.suggest_followup_chat import (
        SuggestFollowupQuesPipeline,
    )

    if not chat_history:
        return default_samples()

    pipe = SuggestFollowupQuesPipeline()
    pipe.lang = SUPPORTED_LANGUAGE_MAP.get(lang or "vi", "Vietnamese")
    resp = pipe([tuple(m) for m in chat_history]).text
    m = re.search(r"\[(.*?)\]", re.sub("\n", "", resp))
    if m:
        try:
            return [[x] for x in json.loads(m.group())]
        except Exception:
            pass
    return default_samples()


@router.get("/suggestions/default")
def get_default():
    return {"suggestions": default_samples()}


@router.post("/conversations/{conv_id}/suggestions")
def suggest(conv_id: str, req: SuggestRequest):
    history = req.chat_history
    if history is None:
        detail = store.get_conversation(conv_id)
        if detail is None:
            raise HTTPException(404, "Conversation not found")
        history = detail.get("messages", [])
    suggestions = generate_suggestions(history, req.language)
    store.save_suggestions(conv_id, suggestions)
    return {"suggestions": suggestions}
