"""Địa điểm xử lý thủ tục gần người dùng — cho tính năng bản đồ của UI React.

POST /api/places/nearby   — danh sách cơ quan/đơn vị gần (lat,lng) + metadata (SerpAPI
                            google_maps; thiếu data → fallback web Brave). Nếu không có
                            lat/lng nhưng có address thì geocode trước.
POST /api/places/geocode  — đổi địa chỉ chữ → toạ độ (Nominatim) cho ô nhập tay.

Tách khỏi backend RAG: chỉ gọi rag/places.py (thuần requests). Xem docs/places-feature.md.
"""
from fastapi import APIRouter, HTTPException

from rag import places as places_mod

from ..schemas import GeocodeRequest, NearbyRequest

router = APIRouter(prefix="/api/places", tags=["places"])


@router.post("/nearby")
def nearby(req: NearbyRequest):
    lat, lng = req.lat, req.lng

    # Không có toạ độ trực tiếp → thử geocode địa chỉ gõ tay.
    if lat is None or lng is None:
        if not req.address:
            raise HTTPException(400, "Cần lat/lng hoặc address để xác định vị trí.")
        geo = places_mod.geocode(req.address)
        if geo is None:
            raise HTTPException(422, f"Không xác định được toạ độ cho: {req.address!r}")
        lat, lng = geo["lat"], geo["lng"]

    if not req.agency.strip():
        raise HTTPException(400, "Thiếu tên cơ quan (agency).")

    try:
        result = places_mod.find_nearby(req.agency, lat, lng, hint=req.hint)
    except RuntimeError as e:  # SERPAPI_KEY chưa cấu hình
        raise HTTPException(503, str(e))
    return result


@router.post("/geocode")
def geocode(req: GeocodeRequest):
    geo = places_mod.geocode(req.address)
    if geo is None:
        raise HTTPException(422, f"Không tìm thấy toạ độ cho: {req.address!r}")
    return geo
