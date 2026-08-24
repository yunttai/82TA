import { useEffect, useRef, useState } from "react";

import { loadKakaoMaps } from "../map/kakaoMaps";
import { decodeGeoJsonLine, decodeStandardPolyline } from "./polyline";
import type { RouteCandidate } from "../../shared/api/publicService";

interface RouteMapProps {
  route: RouteCandidate | null;
  selectedLegId?: string;
}

export function RouteMap({ route, selectedLegId }: RouteMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"READY" | "NO_KEY" | "FAILED">("READY");
  const appKey = import.meta.env.KAKAO_JS_API_KEY;

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

      const routePoints = route.legs.flatMap((leg) => {
        const geometryPoints = leg.geometry.encoding === "GEOJSON"
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
        return [leg.from.coordinate, ...geometryPoints, leg.to.coordinate];
      });

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

      if (maps.LatLngBounds !== undefined && map.setBounds !== undefined) {
        const bounds = new maps.LatLngBounds();
        routePoints.forEach((point) => bounds.extend(new maps.LatLng(point.lat, point.lon)));
        // Fit after every overlay is added so the entire origin-to-destination
        // route remains visible, including geometry that bends beyond endpoints.
        map.setBounds(bounds, 44, 28, 44, 28);
      }
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
          <p>{status === "NO_KEY" ? "현재 지도 연결을 확인할 수 없습니다. 아래 경로 상세를 이용해 주세요." : "지도를 불러오지 못했습니다. 아래 경로 상세를 이용해 주세요."}</p>
        </div>
      )}
      {(missingGeometry > 0 || malformedPolyline > 0 || oversizedPolyline > 0 || malformedGeoJson > 0 || oversizedGeoJson > 0) && (
        <p className="map-disclosure">
          {missingGeometry > 0 && `${missingGeometry}개 구간의 상세 경로선을 제공하지 않습니다. `}
          {malformedGeoJson > 0 && `${malformedGeoJson}개 구간의 상세 경로선을 표시할 수 없습니다. `}
          {oversizedGeoJson > 0 && `${oversizedGeoJson}개 구간의 상세 경로선이 너무 길어 표시하지 않았습니다. `}
          {malformedPolyline > 0 && `${malformedPolyline}개 구간의 상세 경로선을 표시할 수 없습니다. `}
          {oversizedPolyline > 0 && `${oversizedPolyline}개 구간의 상세 경로선이 너무 길어 표시하지 않았습니다.`}
        </p>
      )}
    </section>
  );
}
