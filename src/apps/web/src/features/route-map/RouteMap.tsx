import { useEffect, useRef, useState } from "react";

import { loadKakaoMaps } from "../map/kakaoMaps";
import { decodeGeoJsonLine, decodeStandardPolyline } from "./polyline";
import type { RouteCandidate } from "../../shared/api/publicService";

interface RouteMapProps {
  route: RouteCandidate | null;
  selectedLegId?: string;
}

const modeLabels = {
  WALK: "도보",
  WAIT: "대기",
  TRANSFER: "환승 이동",
  TAXI: "택시",
  BUS: "버스",
  SUBWAY: "지하철",
  GTX: "GTX",
  TRAIN: "기차",
} as const;

export function RouteMap({ route, selectedLegId }: RouteMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"READY" | "NO_KEY" | "FAILED">("READY");
  const appKey = import.meta.env.VITE_KAKAO_MAP_APP_KEY;

  useEffect(() => {
    if (route === null || container.current === null) return undefined;
    if (appKey === undefined || appKey.trim().length === 0) {
      setStatus("NO_KEY");
      return undefined;
    }

    let disposed = false;
    setStatus("READY");
    void loadKakaoMaps(appKey).then((maps) => {
      if (disposed || container.current === null) return;
      const first = route.legs[0]?.from.coordinate;
      const last = route.legs.at(-1)?.to.coordinate;
      if (first === undefined) return;

      container.current.replaceChildren();
      const map = new maps.Map(container.current, {
        center: new maps.LatLng(first.lat, first.lon),
        level: 7,
      });
      new maps.Marker({ map, position: new maps.LatLng(first.lat, first.lon) });
      if (last !== undefined) new maps.Marker({ map, position: new maps.LatLng(last.lat, last.lon) });

      route.legs.forEach((leg) => {
        const line = leg.geometry.encoding === "GEOJSON"
          ? (() => {
              const decoded = decodeGeoJsonLine(leg.geometry.value);
              return decoded.ok ? decoded.points : [];
            })()
          : leg.geometry.encoding === "POLYLINE"
            ? (() => {
                const decoded = decodeStandardPolyline(leg.geometry.value);
                return decoded.ok ? decoded.points : [];
              })()
            : [];
        if (line.length < 2) return;
        new maps.Polyline({
          map,
          path: line.map((point) => new maps.LatLng(point.lat, point.lon)),
          strokeWeight: leg.mode === "WALK" ? 4 : 6,
          strokeColor: leg.legId === selectedLegId ? "#b04a36" : leg.mode === "TAXI" ? "#d85b3f" : leg.mode === "WALK" ? "#63706b" : "#0c473b",
          strokeOpacity: 0.85,
        });
      });
    }).catch(() => {
      if (!disposed) setStatus("FAILED");
    });

    return () => { disposed = true; };
  }, [appKey, route, selectedLegId]);

  if (route === null) {
    return <div className="route-map route-map-empty"><p>추천 카드를 선택하면 지도와 구간을 함께 볼 수 있습니다.</p></div>;
  }

  const missingGeometry = route.legs.filter((leg) => leg.geometry.encoding === "NONE").length;
  const polylineResults = route.legs
    .filter((leg) => leg.geometry.encoding === "POLYLINE")
    .map((leg) => decodeStandardPolyline(leg.geometry.value));
  const malformedPolyline = polylineResults.filter((result) => !result.ok && result.reason === "MALFORMED").length;
  const oversizedPolyline = polylineResults.filter((result) => !result.ok && result.reason === "OVERSIZED").length;
  const geoJsonResults = route.legs
    .filter((leg) => leg.geometry.encoding === "GEOJSON")
    .map((leg) => decodeGeoJsonLine(leg.geometry.value));
  const malformedGeoJson = geoJsonResults.filter((result) => !result.ok && result.reason === "MALFORMED").length;
  const oversizedGeoJson = geoJsonResults.filter((result) => !result.ok && result.reason === "OVERSIZED").length;

  return (
    <section className="route-map" aria-label="선택한 추천 경로 지도">
      <div className="map-canvas" ref={container} aria-hidden={status !== "READY"} />
      {status !== "READY" && (
        <div className="map-fallback" role="status">
          <strong>지도 표시를 사용할 수 없습니다.</strong>
          <p>{status === "NO_KEY" ? "배포 환경의 도메인 제한 Kakao 지도 키가 아직 연결되지 않았습니다." : "지도 SDK를 불러오지 못했습니다."}</p>
        </div>
      )}
      {(missingGeometry > 0 || malformedPolyline > 0 || oversizedPolyline > 0 || malformedGeoJson > 0 || oversizedGeoJson > 0) && (
        <p className="map-disclosure">
          {missingGeometry > 0 && `${missingGeometry}개 구간은 geometry가 없어 지도에 그리지 않았습니다. `}
          {malformedGeoJson > 0 && `${malformedGeoJson}개 GEOJSON 구간은 형식 또는 좌표가 올바르지 않아 표시하지 않았습니다. `}
          {oversizedGeoJson > 0 && `${oversizedGeoJson}개 GEOJSON 구간은 안전한 표시 한도를 넘어 표시하지 않았습니다. `}
          {malformedPolyline > 0 && `${malformedPolyline}개 POLYLINE 구간은 형식 또는 좌표가 올바르지 않아 표시하지 않았습니다. `}
          {oversizedPolyline > 0 && `${oversizedPolyline}개 POLYLINE 구간은 안전한 표시 한도를 넘어 표시하지 않았습니다.`}
        </p>
      )}
      <ol className="map-leg-summary" aria-label="선택 경로 구간 요약">
        {route.legs.map((leg) => (
          <li className={leg.legId === selectedLegId ? "selected-leg" : undefined} aria-current={leg.legId === selectedLegId ? "step" : undefined} key={leg.legId}><strong>{modeLabels[leg.mode]}</strong><span>{leg.from.name} → {leg.to.name}</span></li>
        ))}
      </ol>
    </section>
  );
}
