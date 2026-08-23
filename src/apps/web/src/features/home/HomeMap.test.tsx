import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { KakaoLatLng, KakaoMaps } from "../map/kakaoMaps";
import { HomeMap } from "./HomeMap";

afterEach(() => {
  delete window.kakao;
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("map-first home current location", () => {
  it("keeps the map home focused on the destination entry without a duplicate route card", () => {
    render(<HomeMap />);

    expect(screen.getByRole("link", { name: /어디로 갈까요/ })).toHaveAttribute("href", "/search");
    expect(screen.queryByRole("button", { name: /길찾기 카드/ })).not.toBeInTheDocument();
  });

  it("requests one foreground position after the user action and only centers the Kakao browser map", async () => {
    vi.stubEnv("VITE_KAKAO_MAP_APP_KEY", "browser-domain-key");
    vi.stubGlobal("isSecureContext", true);
    const setCenter = vi.fn();
    const setMarkerPosition = vi.fn();

    class FakeLatLng implements KakaoLatLng {
      constructor(private readonly lat: number, private readonly lon: number) {}
      getLat() { return this.lat; }
      getLng() { return this.lon; }
    }
    class FakeMap {
      constructor(_element: HTMLElement, _options: { center: KakaoLatLng; level: number }) {}
      setCenter(position: KakaoLatLng) { setCenter(position); }
    }
    class FakeMarker {
      constructor(_options: { map: FakeMap; position: KakaoLatLng; draggable?: boolean }) {}
      setPosition(position: KakaoLatLng) { setMarkerPosition(position); }
    }
    class FakePolyline {
      constructor(_options: unknown) {}
    }
    const maps = {
      load: (callback: () => void) => callback(),
      LatLng: FakeLatLng,
      Map: FakeMap,
      Marker: FakeMarker,
      Polyline: FakePolyline,
      event: { addListener: vi.fn(), removeListener: vi.fn() },
    } satisfies KakaoMaps;
    window.kakao = { maps };

    const getCurrentPosition = vi.fn((success: PositionCallback) => {
      success({ coords: { latitude: 37.4, longitude: 127.1 } } as GeolocationPosition);
    });
    vi.stubGlobal("navigator", Object.assign(Object.create(window.navigator), {
      geolocation: { getCurrentPosition },
    }));

    const user = userEvent.setup();
    render(<HomeMap />);
    const locate = screen.getByRole("button", { name: "현재 위치로 지도 이동" });
    await waitFor(() => expect(locate).toBeEnabled());
    await user.click(locate);

    expect(getCurrentPosition).toHaveBeenCalledOnce();
    expect(setCenter).toHaveBeenCalledOnce();
    expect(setMarkerPosition).not.toHaveBeenCalled();
    expect(screen.getByText("현재 위치를 지도 중심으로 옮겼습니다.")).toBeInTheDocument();
  });
});
