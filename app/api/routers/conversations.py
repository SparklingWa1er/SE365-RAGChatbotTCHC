"""CRUD hội thoại."""
from fastapi import APIRouter, HTTPException

from .. import store
from ..schemas import ConversationCreate, ConversationPatch

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
def list_all():
    return {"conversations": store.list_conversations()}


@router.post("")
def create(req: ConversationCreate):
    return store.create_conversation(name=req.name)


@router.get("/{conv_id}")
def detail(conv_id: str):
    d = store.get_conversation(conv_id)
    if d is None:
        raise HTTPException(404, "Conversation not found")
    return d


@router.patch("/{conv_id}")
def patch(conv_id: str, req: ConversationPatch):
    d = store.patch_conversation(conv_id, name=req.name, is_public=req.is_public)
    if d is None:
        raise HTTPException(404, "Conversation not found")
    return d


@router.delete("/{conv_id}")
def delete(conv_id: str):
    if not store.delete_conversation(conv_id):
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}
