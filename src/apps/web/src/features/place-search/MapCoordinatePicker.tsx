import { useEffect, useRef, useState } from "react";

import { loadKakaoMaps, type KakaoLatLng, type KakaoMap, type KakaoMarker } from "../map/kakaoMaps";
import { reverseGeocode, type PlaceRef } from "../../shared/api/publicService";

type Target = "ORIGIN" | "DESTINATION";

interface MapCoordinatePickerProps {
  origin: PlaceRef;
  destination: PlaceRef;
  disabled?: boolean;
  onPlaceSelected: (target: Target, place: PlaceRef) => void;
}

function validCoordinate(coordinate: PlaceRef["coordinate"]): boolean {
  return Number.isFinite(coordinate.lon) && Number.isFinite(coordinate.lat)
    && coordinate.lon >= -180 && coordinate.lon <= 180
    && coordinate.lat >= -90 && coordinate.lat <= 90;
}

export function MapCoordinatePicker({ origin, destination, disabled = false, onPlaceSelected }: MapCoordinatePickerProps) {
  const container = useRef<HTMLDivElement>(null);
  const [target, setTarget] = useState<Target>("ORIGIN");
  const [status, setStatus] = useState<"READY" | "NO_KEY" | "FAILED" | "GEOCODING">("READY");
  const [pendingCoordinate, setPendingCoordinate] = useState<PlaceRef["coordinate"] | null>(null);
  const appKey = import.meta.env.KAKAO_JS_API_KEY;
  const activePlace = target === "ORIGIN" ? origin : destination;

  useEffect(() => {
    if (container.current === null || !validCoordinate(activePlace.coordinate)) return undefined;
    if (appKey === undefined || appKey.trim().length === 0) {
      setStatus("NO_KEY");
      return undefined;
    }

    let disposed = false;
    let map: KakaoMap | null = null;
    let marker: KakaoMarker | null = null;
    let clickHandler: ((event: { latLng?: KakaoLatLng }) => void) | null = null;
    let dragHandler: ((event: { latLng?: KakaoLatLng }) => void) | null = null;
    let mapsApi: Awaited<ReturnType<typeof loadKakaoMaps>> | null = null;
    setStatus("READY");

    function stageCoordinate(position: KakaoLatLng | undefined) {
      if (position === undefined || disposed) return;
      const coordinate = { lon: position.getLng(), lat: position.getLat() };
      if (!validCoordinate(coordinate)) {
        setStatus("FAILED");
        return;
      }
      marker?.setPosition(position);
      map?.setCenter(position);
      setPendingCoordinate(coordinate);
    }

    void loadKakaoMaps(appKey).then((maps) => {
      if (disposed || container.current === null) return;
      mapsApi = maps;
      const position = new maps.LatLng(activePlace.coordinate.lat, activePlace.coordinate.lon);
      container.current.replaceChildren();
      map = new maps.Map(container.current, { center: position, level: 6 });
      marker = new maps.Marker({ map, position, draggable: true });
      clickHandler = (event) => { stageCoordinate(event.latLng); };
      dragHandler = (event) => { stageCoordinate(event.latLng); };
      maps.event.addListener(map, "click", clickHandler);
      maps.event.addListener(marker, "dragend", dragHandler);
    }).catch(() => { if (!disposed) setStatus("FAILED"); });

    return () => {
      disposed = true;
      if (mapsApi !== null && map !== null && clickHandler !== null) mapsApi.event.removeListener(map, "click", clickHandler);
      if (mapsApi !== null && marker !== null && dragHandler !== null) mapsApi.event.removeListener(marker, "dragend", dragHandler);
    };
  }, [activePlace.coordinate.lat, activePlace.coordinate.lon, appKey, onPlaceSelected, target]);

  async function confirmCoordinate() {
    if (pendingCoordinate === null || !validCoordinate(pendingCoordinate)) return;
    setStatus("GEOCODING");
    try {
      const { data, response } = await reverseGeocode(pendingCoordinate);
      onPlaceSelected(target, response.ok && data !== undefined ? data : {
        displayName: target === "ORIGIN" ? "지도에서 선택한 출발지(주소 확인 불가)" : "지도에서 선택한 목적지(주소 확인 불가)",
        coordinate: pendingCoordinate,
      });
    } catch {
      onPlaceSelected(target, {
        displayName: target === "ORIGIN" ? "지도에서 선택한 출발지(주소 확인 불가)" : "지도에서 선택한 목적지(주소 확인 불가)",
        coordinate: pendingCoordinate,
      });
    } finally {
      setPendingCoordinate(null);
      setStatus("READY");
    }
  }

  return (
    <section className="coordinate-picker" aria-labelledby="coordinate-picker-title">
      <div className="coordinate-picker-heading">
        <div><strong id="coordinate-picker-title">지도에서 위치 선택</strong><span id="coordinate-picker-instructions">지도를 누르거나 marker를 끌어 좌표를 선택합니다.</span></div>
        <div className="coordinate-target" role="group" aria-label="지도 선택 대상">
          <button type="button" aria-pressed={target === "ORIGIN"} disabled={disabled} onClick={() => { setTarget("ORIGIN"); setPendingCoordinate(null); }}>출발지</button>
          <button type="button" aria-pressed={target === "DESTINATION"} disabled={disabled} onClick={() => { setTarget("DESTINATION"); setPendingCoordinate(null); }}>목적지</button>
        </div>
      </div>
      <div className="coordinate-map" ref={container} role="group" aria-label={`${target === "ORIGIN" ? "출발지" : "목적지"} 좌표 선택 지도`} aria-describedby="coordinate-picker-instructions" aria-hidden={status === "NO_KEY" || status === "FAILED" ? true : undefined} />
      {status !== "NO_KEY" && status !== "FAILED" && <button className="secondary-button" type="button" disabled={disabled || pendingCoordinate === null || status === "GEOCODING"} onClick={() => void confirmCoordinate()}>{status === "GEOCODING" ? "주소 확인 중…" : "이 위치 선택"}</button>}
      {status === "NO_KEY" && <p className="map-picker-fallback" role="status"><strong>지도 선택을 사용할 수 없습니다.</strong> Kakao 지도 키가 연결되지 않았습니다. 출발지와 목적지 장소 검색을 이용해 주세요.</p>}
      {status === "FAILED" && <p className="map-picker-fallback" role="status"><strong>지도 SDK를 사용할 수 없습니다.</strong> 출발지와 목적지 장소 검색을 이용해 주세요.</p>}
      {status === "GEOCODING" && <p className="place-status" role="status">선택한 좌표의 주소를 Service에서 확인하는 중…</p>}
    </section>
  );
}
