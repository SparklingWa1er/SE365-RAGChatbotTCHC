"""Danh sách index + file (để chọn lọc phạm vi tra cứu)."""
from fastapi import APIRouter, HTTPException

from ..context import get_context

router = APIRouter(prefix="/api/indices", tags=["indices"])


@router.get("")
def list_indices():
    ctx = get_context()
    return {"indices": [{"id": idx.id, "name": idx.name}
                        for idx in ctx.index_manager.indices]}


@router.get("/{index_id}/files")
def list_files(index_id: int):
    from sqlmodel import Session, select

    from ktem.db.models import engine

    ctx = get_context()
    index = next((i for i in ctx.index_manager.indices if i.id == index_id), None)
    if index is None:
        raise HTTPException(404, "Index not found")
    Source = index._resources["Source"]
    with Session(engine) as s:
        rows = s.exec(select(Source)).all()
        return {"files": [{"id": r.id, "name": r.name} for r in rows]}
