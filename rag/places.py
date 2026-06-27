"""Tìm địa điểm xử lý thủ tục gần người dùng — data cho tính năng bản đồ của UI React.

Dùng **SerpAPI engine `google_maps`** (đọc `SERPAPI_KEY` từ `.env`) để lấy danh sách cơ
quan/đơn vị gần một toạ độ, kèm metadata (địa chỉ, toạ độ, SĐT, giờ làm việc, đánh giá).
Khi data SerpAPI không đủ (0 kết quả hoặc kết quả gần nhất quá xa = lệch địa bàn) thì
**fallback sang web search (Brave)** trả các thẻ tham khảo (không có marker bản đồ).

Bài học khảo sát chất lượng data (xem docs/places-feature.md):
  - gps_coordinates/address/title/place_id phủ ~100%; phone ~60–100%; hours ~50–100%.
  - `ll=@lat,lng,ZOOMz` bias ĐÚNG (kết quả sort được theo khoảng cách) NHƯNG zoom càng
    cao (zoom-in) càng dễ trả 0 kết quả: 10–11z cho nhiều kết quả, 13z+ thường rỗng.
  - Truy vấn thưa ("Sở Tư pháp") có thể trả 0; thêm hậu tố " gần đây" cứu được (→ 18).
  → Chiến lược thích nghi `_adaptive_search`: 11z → (q+" gần đây") 11z → 10z → web.

Module chỉ phụ thuộc `requests` + `decouple` (nhẹ) — an toàn để import sớm trong API layer.
"""
from __future__ import annotations

import logging
import math
from typing import Optional
from urllib.parse import quote_plus, urlparse

import requests
from decouple import config

logger = logging.getLogger(__name__)

SERP_ENDPOINT = "https://serpapi.com/search.json"
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

# Kết quả gần nhất xa hơn ngưỡng này (km) ⇒ coi như KHÔNG có văn phòng tại địa bàn
# (SerpAPI lệch sang tỉnh/thành khác) ⇒ kích hoạt fallback web. ~80km ≈ liên tỉnh.
MAX_DISTANCE_KM = 80.0

# Số địa điểm trả về tối đa cho UI (sau khi sort theo khoảng cách).
DEFAULT_LIMIT = 8


# ── tiện ích ────────────────────────────────────────────────────────────────
def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Khoảng cách great-circle (km) giữa hai toạ độ."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def _hours_text(hours) -> Optional[str]:
    """Chuẩn hoá trường `hours` của SerpAPI: có thể là chuỗi ("Đang mở cửa · …") HOẶC
    list [{"thứ hai": "07:30–11:30, 13:00–17:00"}, ...]. Trả chuỗi gọn để hiển thị."""
    if not hours:
        return None
    if isinstance(hours, str):
        return hours
    if isinstance(hours, list):
        parts = []
        for item in hours:
            if isinstance(item, dict):
                for day, val in item.items():
                    parts.append(f"{day.capitalize()}: {val}")
        return "; ".join(parts) if parts else None
    return None


def _directions_url(lat: float, lng: float, dest_lat: float, dest_lng: float,
                    place_id: Optional[str] = None) -> str:
    """Link Google Maps chỉ đường (mở tab ngoài) — dự phòng khi user muốn điều hướng thật."""
    base = "https://www.google.com/maps/dir/?api=1"
    url = f"{base}&origin={lat},{lng}&destination={dest_lat},{dest_lng}"
    if place_id:
        url += f"&destination_place_id={quote_plus(place_id)}"
    return url


def _normalize_place(item: dict, lat: float, lng: float) -> Optional[dict]:
    """SerpAPI local_result → dict địa điểm chuẩn cho FE. Bỏ qua nếu thiếu toạ độ."""
    g = item.get("gps_coordinates") or {}
    dlat, dlng = g.get("latitude"), g.get("longitude")
    if dlat is None or dlng is None:
        return None
    return {
        "place_id": item.get("place_id"),
        "title": item.get("title"),
        "address": item.get("address"),
        "lat": dlat,
        "lng": dlng,
        "distance_km": round(_haversine_km(lat, lng, dlat, dlng), 2),
        "phone": item.get("phone"),
        "hours": _hours_text(item.get("hours")),
        "open_state": item.get("open_state"),
        "rating": item.get("rating"),
        "reviews": item.get("reviews"),
        "type": item.get("type"),
        "website": item.get("website"),
        "thumbnail": item.get("thumbnail"),
        "directions_url": _directions_url(lat, lng, dlat, dlng, item.get("place_id")),
        "is_web": False,
    }


# ── SerpAPI ─────────────────────────────────────────────────────────────────
def _serp_maps(query: str, lat: float, lng: float, zoom: str) -> list[dict]:
    """Một lần gọi SerpAPI google_maps. Trả list local_results (rỗng nếu lỗi/không có)."""
    api_key = config("SERPAPI_KEY", default="")
    if not api_key:
        raise RuntimeError("Chưa cấu hình SERPAPI_KEY trong .env")
    try:
        resp = requests.get(
            SERP_ENDPOINT,
            params={
                "engine": "google_maps",
                "type": "search",
                "q": query,
                "ll": f"@{lat},{lng},{zoom}",
                "hl": "vi",
                "api_key": api_key,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # mạng/quota/key sai → coi như không có kết quả
        logger.warning("SerpAPI google_maps lỗi (%s): %s", query, e)
        return []
    results = data.get("local_results") or data.get("place_results") or []
    if isinstance(results, dict):  # place_results đôi khi là 1 object
        results = [results]
    return results


def _adaptive_search(agency: str, lat: float, lng: float) -> tuple[list[dict], str]:
    """Thử nhiều chiến lược truy vấn (xem docstring module). DISTANCE-AWARE: dừng ngay
    khi có kết quả TRONG địa bàn (≤ MAX_DISTANCE_KM); nếu một chiến lược chỉ ra kết quả
    lệch xa (vd "Sở Tư pháp" trả Sở ở tỉnh khác) thì THỬ TIẾP các chiến lược sau, cuối
    cùng giữ lại kết quả gần nhất tìm được.

    Trả (normalized_places, query_used). Rỗng nếu mọi chiến lược đều không ra.
    """
    attempts = [
        (agency, "11z"),
        (f"{agency} gần đây", "11z"),  # hậu tố cứu query thưa / lệch địa bàn
        (agency, "10z"),               # mở rộng địa bàn
    ]
    best_places: list[dict] = []
    best_query = agency
    best_nearest = float("inf")
    for q, zoom in attempts:
        raw = _serp_maps(q, lat, lng, zoom)
        norm = [p for p in (_normalize_place(it, lat, lng) for it in raw) if p]
        if not norm:
            continue
        norm.sort(key=lambda p: p["distance_km"])
        nearest = norm[0]["distance_km"]
        if nearest <= MAX_DISTANCE_KM:
            return norm, q          # đủ tốt, dừng (tiết kiệm quota SerpAPI)
        if nearest < best_nearest:  # chỉ có kết quả xa → nhớ cái gần nhất, thử tiếp
            best_places, best_query, best_nearest = norm, q, nearest
    return best_places, best_query


# ── fallback web (Brave) ────────────────────────────────────────────────────
def _brave_fallback(agency: str, hint: str = "") -> list[dict]:
    """Khi SerpAPI không đủ: tìm web để có thông tin liên hệ tham khảo (không có marker).

    Trả các thẻ {is_web: True, title, address(snippet), website, ...} — FE hiển thị dưới
    bản đồ như nguồn 🌐 chưa thẩm định. Không có lat/lng nên không cắm marker.
    """
    api_key = config("BRAVE_API_KEY", default="")
    if not api_key:
        return []
    query = f"{agency} {hint} địa chỉ giờ làm việc số điện thoại".strip()
    try:
        resp = requests.get(
            BRAVE_ENDPOINT,
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            params={"q": query, "count": 5},
            timeout=15,
        )
        resp.raise_for_status()
        results = (resp.json().get("web", {}) or {}).get("results", []) or []
    except Exception as e:
        logger.warning("Brave fallback lỗi: %s", e)
        return []

    import html
    import re

    def _strip(t: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()

    cards = []
    for item in results:
        url = item.get("url", "")
        cards.append({
            "place_id": None,
            "title": _strip(item.get("title", "")),
            "address": _strip(item.get("description", "")),
            "lat": None,
            "lng": None,
            "distance_km": None,
            "phone": None,
            "hours": None,
            "open_state": None,
            "rating": None,
            "reviews": None,
            "type": urlparse(url).netloc or "web",
            "website": url,
            "thumbnail": None,
            "directions_url": None,
            "is_web": True,
        })
    return cards


# ── API công khai ───────────────────────────────────────────────────────────
def find_nearby(
    agency: str,
    lat: float,
    lng: float,
    *,
    limit: int = DEFAULT_LIMIT,
    hint: str = "",
) -> dict:
    """Danh sách địa điểm xử lý thủ tục gần (lat,lng) cho cơ quan `agency`.

    Trả dict:
      - places: list địa điểm chuẩn hoá (đã sort theo khoảng cách tăng dần)
      - source: "serpapi" | "web" | "mixed" | "none"
      - sufficient: bool — SerpAPI có trả văn phòng tại địa bàn không
      - query: truy vấn cuối dùng được
      - web_notes: list thẻ web tham khảo (khi fallback)
    """
    places, query_used = _adaptive_search(agency, lat, lng)  # đã chuẩn hoá + sort
    places = places[:limit]

    nearest = places[0]["distance_km"] if places else None
    sufficient = bool(places) and nearest is not None and nearest <= MAX_DISTANCE_KM

    web_notes: list[dict] = []
    source = "serpapi" if sufficient else "none"
    if not sufficient:
        # data không đủ (rỗng hoặc lệch địa bàn) → chủ động tìm web bổ sung
        web_notes = _brave_fallback(agency, hint)
        if web_notes and places:
            source = "mixed"
        elif web_notes:
            source = "web"
        elif places:
            source = "serpapi"  # có kết quả nhưng xa; vẫn trả để user tự đánh giá

    return {
        "places": places,
        "web_notes": web_notes,
        "source": source,
        "sufficient": sufficient,
        "query": query_used,
        "origin": {"lat": lat, "lng": lng},
    }


# ── geocode địa chỉ gõ tay (fallback khi không cho định vị) ──────────────────
def geocode(address: str) -> Optional[dict]:
    """Đổi địa chỉ chữ → toạ độ qua Nominatim (OSM, free, không key).

    Bắt buộc set User-Agent theo policy OSM. Lỗi/không thấy → None.
    """
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1, "countrycodes": "vn"},
            headers={"User-Agent": "dvc-rag-chatbot/1.0 (admin procedure assistant)"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Nominatim geocode lỗi: %s", e)
        return None
    if not data:
        return None
    top = data[0]
    return {
        "lat": float(top["lat"]),
        "lng": float(top["lon"]),
        "display_name": top.get("display_name"),
    }
