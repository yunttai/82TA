import { useEffect, useRef, useState } from "react";

import { loadKakaoMaps, type KakaoMap, type KakaoMarker } from "../map/kakaoMaps";

const DEFAULT_CENTER = { lat: 37.4019, lon: 127.1087 } as const;

type MapStatus = "LOADING" | "READY" | "NO_KEY" | "FAILED";
type LocationStatus = "IDLE" | "REQUESTING" | "LOCATED" | "DENIED" | "UNAVAILABLE" | "TIMEOUT" | "INSECURE";

function locationMessage(status: LocationStatus): string | null {
  switch (status) {
    case "REQUESTING": return "현재 위치를 확인하는 중입니다.";
    case "LOCATED": return "현재 위치를 지도 중심으로 옮겼습니다.";
    case "DENIED": return "위치 권한이 꺼져 있어요. 브라우저 설정을 확인하거나 장소를 검색해 주세요.";
    case "UNAVAILABLE": return "현재 위치를 확인할 수 없어요. 장소 검색으로 계속할 수 있습니다.";
    case "TIMEOUT": return "위치 확인이 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.";
    case "INSECURE": return "현재 위치는 HTTPS 또는 localhost에서 사용할 수 있어요.";
    case "IDLE": return null;
  }
}

export function HomeMap() {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<KakaoMap | null>(null);
  const locationMarker = useRef<KakaoMarker | null>(null);
  const mapsApi = useRef<Awaited<ReturnType<typeof loadKakaoMaps>> | null>(null);
  const [mapStatus, setMapStatus] = useState<MapStatus>("LOADING");
  const [locationStatus, setLocationStatus] = useState<LocationStatus>("IDLE");
  const appKey = import.meta.env.VITE_KAKAO_MAP_APP_KEY;
  const secureLocation = window.isSecureContext === true;
  const geolocationAvailable = "geolocation" in navigator;

  useEffect(() => {
    if (container.current === null) return undefined;
    if (appKey === undefined || appKey.trim().length === 0) {
      setMapStatus("NO_KEY");
      return undefined;
    }

    let disposed = false;
    setMapStatus("LOADING");
    void loadKakaoMaps(appKey).then((loadedMaps) => {
      if (disposed || container.current === null) return;
      mapsApi.current = loadedMaps;
      const center = new loadedMaps.LatLng(DEFAULT_CENTER.lat, DEFAULT_CENTER.lon);
      container.current.replaceChildren();
      map.current = new loadedMaps.Map(container.current, { center, level: 8 });
      setMapStatus("READY");
    }).catch(() => {
      if (!disposed) setMapStatus("FAILED");
    });

    return () => {
      disposed = true;
      map.current = null;
      locationMarker.current = null;
      mapsApi.current = null;
    };
  }, [appKey]);

  function moveToCurrentLocation() {
    if (!secureLocation) {
      setLocationStatus("INSECURE");
      return;
    }
    if (!geolocationAvailable) {
      setLocationStatus("UNAVAILABLE");
      return;
    }

    setLocationStatus("REQUESTING");
    navigator.geolocation.getCurrentPosition((position) => {
      const loadedMaps = mapsApi.current;
      const activeMap = map.current;
      if (loadedMaps === null || activeMap === null) {
        setLocationStatus("UNAVAILABLE");
        return;
      }
      const current = new loadedMaps.LatLng(position.coords.latitude, position.coords.longitude);
      activeMap.setCenter(current);
      if (locationMarker.current === null) {
        locationMarker.current = new loadedMaps.Marker({ map: activeMap, position: current });
      } else {
        locationMarker.current.setPosition(current);
      }
      setLocationStatus("LOCATED");
    }, (error) => {
      if (error.code === error.PERMISSION_DENIED) setLocationStatus("DENIED");
      else if (error.code === error.TIMEOUT) setLocationStatus("TIMEOUT");
      else setLocationStatus("UNAVAILABLE");
    }, { enableHighAccuracy: false, timeout: 8_000, maximumAge: 60_000 });
  }

  const liveLocationMessage = locationMessage(locationStatus);
  const locateDisabled = mapStatus !== "READY" || locationStatus === "REQUESTING" || !secureLocation || !geolocationAvailable;

  return (
    <main id="main-content" className="home-map-page">
      <div
        ref={container}
        className="home-map-canvas"
        role="region"
        aria-label="경기 남부와 서울 이동 지도를 표시하는 카카오 지도"
        aria-busy={mapStatus === "LOADING"}
      />
      <div className="home-map-tone" aria-hidden="true" />

      <a className="home-destination-card" href="/search">
        <span className="home-search-icon" aria-hidden="true">⌕</span>
        <span><strong>어디로 갈까요?</strong><small>목적지를 정하고 예산 맞춤 경로 찾기</small></span>
        <span className="home-search-arrow" aria-hidden="true">→</span>
      </a>

      <button
        className="home-locate-button"
        type="button"
        disabled={locateDisabled}
        aria-label="현재 위치로 지도 이동"
        onClick={moveToCurrentLocation}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></svg>
      </button>

      {mapStatus !== "READY" && (
        <div className="home-map-fallback" role="status">
          <span aria-hidden="true">82</span>
          <strong>{mapStatus === "LOADING" ? "지도를 준비하고 있어요" : "지도를 불러오지 못했어요"}</strong>
          <small>{mapStatus === "NO_KEY" ? "카카오 지도 키를 연결하면 이 화면에서 바로 지도를 볼 수 있어요." : mapStatus === "FAILED" ? "도메인 설정과 네트워크를 확인해 주세요. 길찾기는 계속 사용할 수 있습니다." : "잠시만 기다려 주세요."}</small>
        </div>
      )}

      {(!secureLocation || liveLocationMessage !== null) && (
        <p className="home-location-status" role="status">
          {liveLocationMessage ?? "현재 위치는 HTTPS 또는 localhost에서 사용할 수 있어요."}
        </p>
      )}

    </main>
  );
}
