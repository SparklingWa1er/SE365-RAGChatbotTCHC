"""Pydantic schema request/response cho API."""
from typing import Optional

from pydantic import BaseModel, Field


class SettingsOverride(BaseModel):
    reasoning_type: Optional[str] = None  # "ReAct" | "simple" | "decompose" | "ReWOO"
    llm: Optional[str] = None
    language: Optional[str] = None        # "vi" | "en" ...
    use_mindmap: Optional[bool] = None
    use_citation: Optional[str] = None    # "inline" | "off"


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    settings_override: Optional[SettingsOverride] = None
    selected_file_ids: list[str] = Field(default_factory=list)
    regen: bool = False


class ConversationCreate(BaseModel):
    name: Optional[str] = None


class ConversationPatch(BaseModel):
    name: Optional[str] = None
    is_public: Optional[bool] = None


class ConversationSummary(BaseModel):
    id: str
    name: str
    date_updated: Optional[str] = None


class ConversationDetail(BaseModel):
    id: str
    name: str
    is_public: bool
    messages: list[list[str]]            # [[user, bot], ...]
    chat_suggestions: list[list[str]]
    selected: dict = Field(default_factory=dict)
    reasoning: list[str] = Field(default_factory=list)  # HTML suy luận theo từng lượt
    citations: list[list[dict]] = Field(default_factory=list)  # nguồn theo từng lượt


class SuggestRequest(BaseModel):
    # nếu không truyền, dùng lịch sử lưu trong conversation
    chat_history: Optional[list[list[str]]] = None
    language: Optional[str] = None


# ── Tính năng bản đồ: địa điểm xử lý thủ tục gần người dùng ──────────────────
class NearbyRequest(BaseModel):
    """Tìm địa điểm cho cơ quan `agency` quanh (lat,lng). Nếu thiếu lat/lng nhưng có
    `address` thì server tự geocode (Nominatim)."""
    agency: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = None     # địa chỉ gõ tay (fallback khi không cho định vị)
    hint: str = ""                    # bối cảnh thêm cho fallback web (vd tên thủ tục)


class GeocodeRequest(BaseModel):
    address: str
