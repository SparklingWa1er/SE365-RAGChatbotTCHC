"""CRUD hội thoại trên ktem DB (sql.db) — tái dùng model Conversation của ktem.

data_source (JSON) chứa: messages [[user,bot],...], selected{}, chat_suggestions,
retrieval_messages [html,...], plot_history, state. Xem control.py:select_conv.
"""
from copy import deepcopy
from typing import Optional

from .context import DEFAULT_USER_ID


def _imports():
    from ktem.db.models import Conversation, engine
    from sqlmodel import Session, select
    return Conversation, engine, Session, select


def get_user_setting(user_id: str = DEFAULT_USER_ID) -> dict:
    """Setting đã lưu của user (chỉ phần override). {} nếu chưa có."""
    from ktem.db.models import Settings, engine
    from sqlmodel import Session, select

    with Session(engine) as s:
        r = s.exec(select(Settings).where(Settings.user == user_id)).first()
        return (r.setting or {}) if r else {}


def save_user_setting(setting: dict, user_id: str = DEFAULT_USER_ID) -> dict:
    """Ghi đè setting override của user."""
    from ktem.db.models import Settings, engine
    from sqlmodel import Session, select

    with Session(engine) as s:
        r = s.exec(select(Settings).where(Settings.user == user_id)).first()
        if r is None:
            r = Settings(user=user_id, setting=setting)
        else:
            r.setting = setting
        s.add(r)
        s.commit()
        return setting


def list_conversations(user_id: str = DEFAULT_USER_ID) -> list[dict]:
    Conversation, engine, Session, select = _imports()
    with Session(engine) as s:
        rows = s.exec(
            select(Conversation)
            .where(Conversation.user == user_id)
            .order_by(Conversation.date_updated.desc())  # type: ignore
        ).all()
        return [
            {"id": r.id, "name": r.name,
             "date_updated": r.date_updated.isoformat() if r.date_updated else None}
            for r in rows
        ]


def create_conversation(name: Optional[str] = None,
                        user_id: str = DEFAULT_USER_ID) -> dict:
    Conversation, engine, Session, _ = _imports()
    with Session(engine) as s:
        conv = Conversation(user=user_id, data_source={"messages": []})
        if name:
            conv.name = name
        s.add(conv)
        s.commit()
        s.refresh(conv)
        return {"id": conv.id, "name": conv.name}


def get_conversation(conv_id: str) -> Optional[dict]:
    Conversation, engine, Session, select = _imports()
    with Session(engine) as s:
        r = s.exec(select(Conversation).where(Conversation.id == conv_id)).first()
        if r is None:
            return None
        ds = r.data_source or {}
        return {
            "id": r.id,
            "name": r.name,
            "is_public": r.is_public,
            "messages": ds.get("messages", []),
            "chat_suggestions": ds.get("chat_suggestions", []),
            "selected": ds.get("selected", {}),
            # HTML các bước suy luận (Thought/Action/Observation + nguồn) theo từng lượt,
            # khớp 1-1 với messages — dùng để hiện lại dropdown suy luận khi tải lại trang.
            "reasoning": ds.get("retrieval_messages", []),
            # Danh sách nguồn (citations) theo từng lượt, khớp 1-1 với messages —
            # dùng để khôi phục panel "Nguồn" bên phải khi mở lại hội thoại.
            "citations": ds.get("citations_messages", []),
        }


def patch_conversation(conv_id: str, name: Optional[str] = None,
                       is_public: Optional[bool] = None) -> Optional[dict]:
    Conversation, engine, Session, select = _imports()
    with Session(engine) as s:
        r = s.exec(select(Conversation).where(Conversation.id == conv_id)).first()
        if r is None:
            return None
        if name is not None:
            r.name = name
        if is_public is not None:
            r.is_public = is_public
        s.add(r)
        s.commit()
        s.refresh(r)
        return {"id": r.id, "name": r.name, "is_public": r.is_public}


def delete_conversation(conv_id: str) -> bool:
    Conversation, engine, Session, select = _imports()
    with Session(engine) as s:
        r = s.exec(select(Conversation).where(Conversation.id == conv_id)).first()
        if r is None:
            return False
        s.delete(r)
        s.commit()
        return True


def append_message(conv_id: str, user_msg: str, bot_msg: str,
                   info_html: str = "", citations: Optional[list] = None) -> None:
    """Lưu một lượt hỏi-đáp vào data_source.messages (+ retrieval_messages + citations)."""
    Conversation, engine, Session, select = _imports()
    with Session(engine) as s:
        r = s.exec(select(Conversation).where(Conversation.id == conv_id)).first()
        if r is None:
            return
        ds = deepcopy(r.data_source or {})
        ds.setdefault("messages", []).append([user_msg, bot_msg])
        ds.setdefault("retrieval_messages", []).append(info_html)
        ds.setdefault("citations_messages", []).append(citations or [])
        r.data_source = ds
        s.add(r)
        s.commit()


def drop_last_message(conv_id: str) -> Optional[list[str]]:
    """Bỏ lượt hỏi-đáp cuối (cho regen). Trả [user, bot] vừa bỏ, hoặc None."""
    Conversation, engine, Session, select = _imports()
    with Session(engine) as s:
        r = s.exec(select(Conversation).where(Conversation.id == conv_id)).first()
        if r is None:
            return None
        ds = deepcopy(r.data_source or {})
        msgs = ds.get("messages", [])
        if not msgs:
            return None
        popped = msgs.pop()
        if ds.get("retrieval_messages"):
            ds["retrieval_messages"].pop()
        if ds.get("citations_messages"):
            ds["citations_messages"].pop()
        ds["messages"] = msgs
        r.data_source = ds
        s.add(r)
        s.commit()
        return popped


def save_suggestions(conv_id: str, suggestions: list[list[str]]) -> None:
    Conversation, engine, Session, select = _imports()
    with Session(engine) as s:
        r = s.exec(select(Conversation).where(Conversation.id == conv_id)).first()
        if r is None:
            return
        ds = deepcopy(r.data_source or {})
        ds["chat_suggestions"] = suggestions
        r.data_source = ds
        s.add(r)
        s.commit()
