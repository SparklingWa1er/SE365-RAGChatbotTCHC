import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Place } from "../api/types";

interface Props {
  origin: { lat: number; lng: number };
  places: Place[]; // chỉ những place CÓ lat/lng được cắm marker
  selectedId: string | null; // place_id đang chọn → vẽ đường đi
  onSelect: (placeId: string) => void;
  // Báo lại quãng đường/thời gian khi đã tính được route (m, giây).
  onRouteInfo?: (info: { distanceKm: number; durationMin: number } | null) => void;
}

// Pin SVG inline → không phụ thuộc asset ảnh của Leaflet (vốn vỡ đường dẫn khi bundle).
function pinIcon(color: string, size = 30): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="${color}"
      stroke="white" stroke-width="1.5" style="filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))">
      <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/>
      <circle cx="12" cy="9" r="2.5" fill="white" stroke="none"/></svg>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size], // mũi pin chạm điểm
    popupAnchor: [0, -size],
  });
}

function dotIcon(): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div style="width:16px;height:16px;border-radius:9999px;background:#1668c9;
      border:3px solid white;box-shadow:0 0 0 2px rgba(22,104,201,.4),0 1px 3px rgba(0,0,0,.4)"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

export default function MapView({
  origin,
  places,
  selectedId,
  onSelect,
  onRouteInfo,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markersRef = useRef<Map<string, L.Marker>>(new Map());
  const routeRef = useRef<L.GeoJSON | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // ── khởi tạo map MỘT lần ──
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true, attributionControl: true });
    L.tileLayer(TILE_URL, { attribution: TILE_ATTR, maxZoom: 19 }).addTo(map);
    map.setView([origin.lat, origin.lng], 13);
    mapRef.current = map;
    // Leaflet đo sai kích thước khi container vừa hiện trong dialog → ép tính lại.
    setTimeout(() => map.invalidateSize(), 0);
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── vẽ lại markers khi origin/places đổi ──
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current.clear();

    // marker người dùng
    L.marker([origin.lat, origin.lng], { icon: dotIcon(), zIndexOffset: 1000 })
      .addTo(map)
      .bindPopup("Vị trí của bạn");

    const pts: L.LatLngExpression[] = [[origin.lat, origin.lng]];
    places.forEach((p) => {
      if (p.lat == null || p.lng == null || !p.place_id) return;
      const marker = L.marker([p.lat, p.lng], { icon: pinIcon("#dc2626") })
        .addTo(map)
        .bindPopup(
          `<b>${p.title ?? ""}</b><br>${p.address ?? ""}` +
            (p.distance_km != null ? `<br>${p.distance_km} km` : ""),
        );
      marker.on("click", () => onSelectRef.current(p.place_id!));
      markersRef.current.set(p.place_id, marker);
      pts.push([p.lat, p.lng]);
    });

    if (pts.length > 1) {
      map.fitBounds(L.latLngBounds(pts), { padding: [40, 40], maxZoom: 15 });
    } else {
      map.setView([origin.lat, origin.lng], 13);
    }
  }, [origin, places]);

  // ── vẽ đường đi tới place đang chọn (OSRM) ──
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // bỏ route cũ
    if (routeRef.current) {
      routeRef.current.remove();
      routeRef.current = null;
    }
    // tô đậm pin đang chọn
    markersRef.current.forEach((m, id) =>
      m.setIcon(id === selectedId ? pinIcon("#1668c9", 38) : pinIcon("#dc2626")),
    );

    const place = places.find((p) => p.place_id === selectedId);
    if (!place || place.lat == null || place.lng == null) {
      onRouteInfo?.(null);
      return;
    }

    map.getPane("popupPane"); // noop giữ ref ổn định
    markersRef.current.get(selectedId!)?.openPopup();

    let cancelled = false;
    const url =
      `https://router.project-osrm.org/route/v1/driving/` +
      `${origin.lng},${origin.lat};${place.lng},${place.lat}` +
      `?overview=full&geometries=geojson`;

    fetch(url)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        const route = data?.routes?.[0];
        if (!route) {
          onRouteInfo?.(null);
          return;
        }
        routeRef.current = L.geoJSON(route.geometry, {
          style: { color: "#1668c9", weight: 5, opacity: 0.8 },
        }).addTo(map);
        map.fitBounds(routeRef.current.getBounds(), { padding: [50, 50], maxZoom: 16 });
        onRouteInfo?.({
          distanceKm: route.distance / 1000,
          durationMin: route.duration / 60,
        });
      })
      .catch(() => !cancelled && onRouteInfo?.(null));

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, places, origin]);

  return <div ref={containerRef} className="h-full w-full" />;
}
