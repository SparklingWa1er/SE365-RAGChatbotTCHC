# Tính năng "Địa điểm xử lý thủ tục gần bạn" (bản đồ)

Tính năng cho phép người dùng, sau khi nhận câu trả lời về một thủ tục, bấm **"📍 Địa
điểm xử lý gần bạn"** → cấp vị trí (định vị trình duyệt hoặc nhập địa chỉ) → xem danh
sách cơ quan/đơn vị gần đó kèm **địa chỉ, SĐT, giờ làm việc, đánh giá**, và **bản đồ +
đường đi** từ vị trí của mình tới địa điểm được chọn.

> Đây là tính năng **FE-điều phối có data-endpoint backend**, KHÔNG phải một ReAct tool:
> vị trí đến từ trình duyệt (`navigator.geolocation`) và UI là bản đồ tương tác — hai thứ
> vòng lặp ReAct đồng bộ không xử lý tự nhiên được.

---

## Luồng

```
[Câu trả lời thủ tục xong]
   │  ChatView: nút "📍 Địa điểm xử lý gần bạn" (hiện khi đã có lượt)
   ▼ user bấm → App.openMap(): guessAgency(turns) + hint = câu hỏi gần nhất
PlacesDialog (modal):
   │  tự định vị navigator.geolocation  (fallback: ô nhập địa chỉ → /api/places/geocode)
   ▼  POST /api/places/nearby {agency, lat, lng, hint}
app/api/routers/places.py → rag/places.find_nearby()
   │  SerpAPI engine=google_maps (adaptive) → chuẩn hoá + sort theo khoảng cách
   │  thiếu data → fallback Brave web (thẻ tham khảo 🌐)
   ▼  JSON {places[], web_notes[], source, sufficient, ...}
PlacesDialog: danh sách (trái) + MapView (phải)
   ▼ user bấm 1 địa điểm
MapView (Leaflet vanilla): markers + OSRM route → "x km · ~y phút lái xe"
```

## API dùng (đều free, không billing)

| Nhu cầu | API | Ghi chú |
|---|---|---|
| Danh sách địa điểm + metadata | **SerpAPI `google_maps`** (`SERPAPI_KEY`) | gps/address/title/place_id ~100%, phone/hours đa số. Free ~100 search/tháng. |
| Tile bản đồ | **OpenStreetMap** qua **Leaflet** (vanilla) | không key. Dùng Leaflet trực tiếp (không react-leaflet) tránh xung đột peer-dep React 19. |
| Đường đi (route + km + phút) | **OSRM** demo (`router.project-osrm.org`) | không key. *Demo server không cho production.* |
| Geocode địa chỉ gõ tay | **Nominatim** (OSM) | không key; cần `User-Agent`, ≤1 req/s. |
| Fallback khi SerpAPI thiếu | **Brave Search** (`BRAVE_API_KEY`, tái dùng) | thẻ web 🌐 chưa thẩm định, không marker. |

## Bài học khảo sát chất lượng data SerpAPI (đã kiểm chứng thực)

- `ll=@lat,lng,ZOOMz` **bias đúng** (kết quả sort được theo khoảng cách), NHƯNG **zoom càng
  cao càng dễ trả 0 kết quả**: `10–11z` cho nhiều kết quả, `13z+` thường rỗng.
- Truy vấn **thưa/lệch** ("Sở Tư pháp" có thể trả Sở ở tỉnh khác hoặc 0) → thêm hậu tố
  **" gần đây"** cứu được (vd 0 → 18 kết quả).
- → `rag/places._adaptive_search` **distance-aware**: thử `agency@11z` → nếu kết quả gần
  nhất > `MAX_DISTANCE_KM` (80km) thì thử `agency gần đây@11z` → `agency@10z`; chọn lượt có
  kết quả gần địa bàn nhất. Hết cách → `sufficient=False` → fallback web.

## File liên quan

**Backend**
- `rag/places.py` — `find_nearby()`, `geocode()`, `_adaptive_search()`, chuẩn hoá `hours`
  (chuỗi HOẶC list), tính haversine, dựng `directions_url` (Google Maps).
- `app/api/routers/places.py` — `POST /api/places/nearby`, `POST /api/places/geocode`.
- `app/api/schemas.py` — `NearbyRequest`, `GeocodeRequest`.
- `app/api/main.py` — đăng ký router `places`.

**Frontend**
- `frontend/src/components/PlacesDialog.tsx` — điều phối: định vị, gọi API, danh sách + map.
- `frontend/src/components/MapView.tsx` — Leaflet vanilla: markers (pin SVG inline) + OSRM route.
- `frontend/src/lib/places.ts` — `guessAgency()` đoán cơ quan từ hội thoại (bỏ ký hiệu 【n】).
- `frontend/src/api/{client,types}.ts` — `nearbyPlaces()`, `geocodePlace()` + kiểu `Place`/`NearbyResult`.
- `frontend/src/components/{ChatView,Composer}.tsx` — nút "📍 Địa điểm xử lý gần bạn".

## Lưu ý / giới hạn

- **Geolocation cần HTTPS hoặc `localhost`** — host LAN bằng IP thì trình duyệt chặn
  `getCurrentPosition` → phải dùng ô nhập địa chỉ (Nominatim). Dialog đã có fallback này.
- SerpAPI **100 search/tháng** → chỉ gọi khi user **chủ động bấm** (không tự gọi mỗi câu).
  Có thể thêm cache theo (agency, ô lưới toạ độ) nếu cần tiết kiệm thêm.
- OSRM/Nominatim public **không SLA** — hợp demo, không hợp production.
- Địa điểm từ Google Maps **chưa thẩm định** (như nguồn 🌐) — chỉ tham khảo.
- `guessAgency` chỉ là heuristic prefill; ô cơ quan luôn **sửa được** trong dialog.
