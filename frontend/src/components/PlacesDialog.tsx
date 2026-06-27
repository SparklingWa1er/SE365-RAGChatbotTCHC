import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Clock,
  Globe,
  LoaderCircle,
  MapPin,
  Navigation,
  Phone,
  Search,
  Star,
} from "lucide-react";
import * as api from "../api/client";
import type { NearbyResult, Place } from "../api/types";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import MapView from "./MapView";

interface Props {
  open: boolean;
  initialAgency: string;
  hint?: string; // bối cảnh thêm (tên thủ tục) cho fallback web
  onClose: () => void;
}

type Origin = { lat: number; lng: number } | null;

// Dialog "Địa điểm xử lý thủ tục gần bạn": xin vị trí (định vị trình duyệt hoặc nhập
// địa chỉ) → gọi /api/places/nearby → danh sách bên trái + bản đồ + đường đi bên phải.
export default function PlacesDialog({ open, initialAgency, hint, onClose }: Props) {
  const [agency, setAgency] = useState(initialAgency);
  const [origin, setOrigin] = useState<Origin>(null);
  const [address, setAddress] = useState("");
  const [locating, setLocating] = useState(false);
  const [locError, setLocError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<NearbyResult | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [routeInfo, setRouteInfo] =
    useState<{ distanceKm: number; durationMin: number } | null>(null);
  const triedAuto = useRef(false);

  // gọi API với một origin cụ thể
  const fetchNearby = useCallback(
    async (o: { lat: number; lng: number }, ag: string) => {
      if (!ag.trim()) {
        setError("Hãy nhập tên cơ quan/đơn vị cần tìm.");
        return;
      }
      setLoading(true);
      setError("");
      setResult(null);
      setSelectedId(null);
      setRouteInfo(null);
      try {
        const r = await api.nearbyPlaces({
          agency: ag.trim(),
          lat: o.lat,
          lng: o.lng,
          hint,
        });
        setResult(r);
        if (r.places[0]?.place_id) setSelectedId(r.places[0].place_id);
      } catch (e) {
        setError((e as Error).message || "Không tải được danh sách địa điểm.");
      } finally {
        setLoading(false);
      }
    },
    [hint],
  );

  // định vị qua trình duyệt. agencyOverride: khi gọi tự động lúc mở dialog, `agency`
  // state có thể chưa cập nhật (race với setAgency) → truyền thẳng initialAgency.
  const useMyLocation = useCallback((agencyOverride?: string) => {
    const ag = agencyOverride ?? agency;
    setLocError("");
    if (!("geolocation" in navigator)) {
      setLocError("Trình duyệt không hỗ trợ định vị. Hãy nhập địa chỉ bên dưới.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        const o = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setOrigin(o);
        fetchNearby(o, ag);
      },
      (err) => {
        setLocating(false);
        setLocError(
          err.code === err.PERMISSION_DENIED
            ? "Bạn đã từ chối định vị. Hãy nhập địa chỉ bên dưới."
            : "Không lấy được vị trí. Hãy nhập địa chỉ bên dưới.",
        );
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }, [agency, fetchNearby]);

  // geocode địa chỉ gõ tay → origin → fetch
  const useTypedAddress = useCallback(async () => {
    if (!address.trim()) return;
    setLocating(true);
    setLocError("");
    try {
      const g = await api.geocodePlace(address.trim());
      const o = { lat: g.lat, lng: g.lng };
      setOrigin(o);
      fetchNearby(o, agency);
    } catch {
      setLocError(`Không tìm thấy toạ độ cho "${address}". Thử địa chỉ cụ thể hơn.`);
    } finally {
      setLocating(false);
    }
  }, [address, agency, fetchNearby]);

  // reset khi mở; tự thử định vị một lần
  useEffect(() => {
    if (!open) {
      triedAuto.current = false;
      return;
    }
    setAgency(initialAgency);
    if (!triedAuto.current) {
      triedAuto.current = true;
      // thử định vị tự động (không chặn — user vẫn thấy ô nhập tay nếu từ chối).
      // Truyền initialAgency vì state `agency` vừa setAgency chưa kịp cập nhật.
      useMyLocation(initialAgency);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialAgency]);

  // Memoize: nếu tạo mảng mới mỗi render, useEffect trong MapView lệ thuộc `places` sẽ
  // chạy lại liên tục → fitBounds lặp → BẢN ĐỒ ZOOM IN KHÔNG NGỪNG. Chỉ đổi khi result đổi.
  const mapPlaces = useMemo(
    () => result?.places.filter((p) => p.lat != null && p.lng != null) ?? [],
    [result],
  );

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        showCloseButton
        className="flex h-[82vh] w-[min(96vw,1120px)] max-w-none flex-col gap-0 overflow-hidden p-0 sm:max-w-none"
      >
        {/* Header */}
        <div className="flex flex-col gap-2.5 border-b border-border p-4">
          <DialogTitle className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <MapPin className="size-4 text-primary" />
            Địa điểm xử lý thủ tục gần bạn
          </DialogTitle>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[240px] flex-1">
              <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={agency}
                onChange={(e) => setAgency(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && origin) fetchNearby(origin, agency);
                }}
                placeholder="Cơ quan/đơn vị (vd: Phòng Quản lý xuất nhập cảnh)"
                className="h-9 pl-8 text-sm"
              />
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={locating}
              onClick={() => useMyLocation()}
              className="h-9 gap-1.5"
            >
              {locating ? (
                <LoaderCircle className="size-3.5 animate-spin" />
              ) : (
                <Navigation className="size-3.5" />
              )}
              Vị trí của tôi
            </Button>
            <Button
              size="sm"
              disabled={!origin || loading || !agency.trim()}
              onClick={() => origin && fetchNearby(origin, agency)}
              className="h-9"
            >
              Tìm
            </Button>
          </div>

          {/* fallback nhập địa chỉ khi chưa có vị trí / bị từ chối */}
          {(!origin || locError) && (
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && useTypedAddress()}
                placeholder="…hoặc nhập địa chỉ của bạn (vd: Quận 1, TP.HCM)"
                className="h-8 min-w-[240px] flex-1 text-sm"
              />
              <Button
                size="sm"
                variant="outline"
                disabled={!address.trim() || locating}
                onClick={useTypedAddress}
                className="h-8"
              >
                Dùng địa chỉ này
              </Button>
            </div>
          )}
          {locError && <p className="text-xs text-amber-600">{locError}</p>}
          {result && !result.sufficient && (
            <p className="text-xs text-amber-600">
              Không thấy {agency} ngay tại địa bàn — hiển thị kết quả gần nhất
              {result.web_notes.length > 0 && " + nguồn web tham khảo (🌐 chưa thẩm định)"}.
            </p>
          )}
        </div>

        {/* Body: danh sách | bản đồ */}
        <div className="flex min-h-0 flex-1">
          <div className="flex w-[340px] shrink-0 flex-col border-r border-border">
            <ScrollArea className="min-h-0 flex-1">
              <div className="flex flex-col gap-2 p-3">
                {loading && (
                  <div className="flex items-center gap-2 px-1 py-6 text-sm text-muted-foreground">
                    <LoaderCircle className="size-4 animate-spin" /> Đang tìm địa điểm…
                  </div>
                )}
                {error && <p className="px-1 py-4 text-sm text-destructive">{error}</p>}
                {!loading && !error && !result && (
                  <p className="px-1 py-6 text-xs text-muted-foreground">
                    Cho phép định vị hoặc nhập địa chỉ để xem các địa điểm gần bạn.
                  </p>
                )}
                {result?.places.map((p) => (
                  <PlaceCard
                    key={p.place_id ?? p.title}
                    p={p}
                    active={p.place_id === selectedId}
                    onClick={() => p.place_id && setSelectedId(p.place_id)}
                  />
                ))}
                {result && result.places.length === 0 && (
                  <p className="px-1 py-4 text-sm text-muted-foreground">
                    Không có địa điểm nào trên bản đồ.
                  </p>
                )}

                {/* nguồn web tham khảo (không có toạ độ) */}
                {result?.web_notes.map((w, i) => (
                  <WebNoteCard key={`w${i}`} w={w} />
                ))}
              </div>
            </ScrollArea>
          </div>

          {/* bản đồ */}
          <div className="relative min-w-0 flex-1 bg-muted">
            {origin && mapPlaces.length > 0 ? (
              <MapView
                origin={origin}
                places={mapPlaces}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onRouteInfo={setRouteInfo}
              />
            ) : (
              <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
                {origin
                  ? "Chưa có địa điểm để hiển thị trên bản đồ."
                  : "Bản đồ sẽ hiện sau khi xác định vị trí của bạn."}
              </div>
            )}

            {/* badge quãng đường / thời gian */}
            {routeInfo && (
              <div className="absolute top-3 left-1/2 z-[500] -translate-x-1/2 rounded-full border border-border bg-card/95 px-3 py-1 text-xs font-medium shadow-sm backdrop-blur">
                <Navigation className="mr-1 inline size-3 text-primary" />
                {routeInfo.distanceKm.toFixed(1)} km · ~{Math.round(routeInfo.durationMin)} phút
                lái xe
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function PlaceCard({
  p,
  active,
  onClick,
}: {
  p: Place;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-col gap-1 rounded-lg border p-2.5 text-left transition",
        active
          ? "border-primary bg-primary/5 ring-1 ring-primary/30"
          : "border-border hover:bg-muted/50",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 break-words text-sm font-medium leading-snug text-foreground">
          {p.title}
        </span>
        {p.distance_km != null && (
          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            {p.distance_km} km
          </span>
        )}
      </div>
      {p.address && (
        <span className="break-words text-[11px] leading-snug text-muted-foreground">
          {p.address}
        </span>
      )}
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[11px] text-muted-foreground">
        {p.rating != null && (
          <span className="inline-flex items-center gap-0.5 text-amber-600">
            <Star className="size-3 fill-amber-500 stroke-amber-500" />
            {p.rating}
            {p.reviews != null && ` (${p.reviews})`}
          </span>
        )}
        {p.open_state && (
          <span className="inline-flex items-center gap-0.5">
            <Clock className="size-3" />
            {p.open_state}
          </span>
        )}
      </div>
      {(p.phone || p.directions_url) && (
        <div className="mt-0.5 flex flex-wrap items-center gap-3 text-[11px]">
          {p.phone && (
            <a
              href={`tel:${p.phone}`}
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              <Phone className="size-3" /> {p.phone}
            </a>
          )}
          {p.directions_url && (
            <a
              href={p.directions_url}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              <Navigation className="size-3" /> Chỉ đường ↗
            </a>
          )}
        </div>
      )}
    </button>
  );
}

function WebNoteCard({ w }: { w: Place }) {
  return (
    <a
      href={w.website ?? "#"}
      target="_blank"
      rel="noreferrer"
      className="flex flex-col gap-1 rounded-lg border border-amber-200 bg-amber-50/50 p-2.5 text-left hover:bg-amber-50"
    >
      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-amber-700">
        <Globe className="size-3" /> web · chưa thẩm định
      </span>
      <span className="break-words text-sm font-medium leading-snug text-foreground">
        {w.title}
      </span>
      {w.address && (
        <span className="line-clamp-2 break-words text-[11px] leading-snug text-muted-foreground">
          {w.address}
        </span>
      )}
    </a>
  );
}
