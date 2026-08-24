export interface KakaoLatLng {
  getLat: () => number;
  getLng: () => number;
}

export interface KakaoLatLngBounds {
  extend: (position: KakaoLatLng) => void;
}

export interface KakaoMap {
  setCenter: (position: KakaoLatLng) => void;
  setBounds?: (
    bounds: KakaoLatLngBounds,
    paddingTop?: number,
    paddingRight?: number,
    paddingBottom?: number,
    paddingLeft?: number,
  ) => void;
}

export interface KakaoMarker {
  setPosition: (position: KakaoLatLng) => void;
}

export interface KakaoMaps {
  load: (callback: () => void) => void;
  LatLng: new (lat: number, lon: number) => KakaoLatLng;
  LatLngBounds?: new () => KakaoLatLngBounds;
  Map: new (element: HTMLElement, options: { center: KakaoLatLng; level: number }) => KakaoMap;
  Marker: new (options: { map: KakaoMap; position: KakaoLatLng; draggable?: boolean }) => KakaoMarker;
  Polyline: new (options: { map: KakaoMap; path: KakaoLatLng[]; strokeWeight: number; strokeColor: string; strokeOpacity: number }) => unknown;
  event: {
    addListener: (target: object, event: string, handler: (event: { latLng?: KakaoLatLng }) => void) => void;
    removeListener: (target: object, event: string, handler: (event: { latLng?: KakaoLatLng }) => void) => void;
  };
}

declare global {
  interface Window {
    kakao?: { maps?: KakaoMaps };
  }
}

let kakaoScript: Promise<KakaoMaps> | null = null;

export function loadKakaoMaps(appKey: string): Promise<KakaoMaps> {
  if (window.kakao?.maps !== undefined) return Promise.resolve(window.kakao.maps);
  if (kakaoScript !== null) return kakaoScript;

  kakaoScript = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&appkey=${encodeURIComponent(appKey)}`;
    script.async = true;
    script.addEventListener("load", () => {
      const maps = window.kakao?.maps;
      if (maps === undefined) {
        reject(new Error("Kakao Maps unavailable"));
        return;
      }
      maps.load(() => resolve(maps));
    }, { once: true });
    script.addEventListener("error", () => reject(new Error("Kakao Maps failed to load")), { once: true });
    document.head.append(script);
  });

  return kakaoScript;
}
