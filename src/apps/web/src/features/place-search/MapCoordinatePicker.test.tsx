import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { KakaoLatLng, KakaoMaps } from "../map/kakaoMaps";
import { MapCoordinatePicker } from "./MapCoordinatePicker";

const origin = { displayName: "출발", coordinate: { lon: 127.1, lat: 37.3 } };
const destination = { displayName: "도착", coordinate: { lon: 127.2, lat: 37.4 } };

afterEach(() => {
  delete window.kakao;
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("input map coordinate picker", () => {
  it("keeps place-search fallback when the browser map key is absent", () => {
    vi.stubEnv("KAKAO_JS_API_KEY", "");
    render(<MapCoordinatePicker origin={origin} destination={destination} onPlaceSelected={vi.fn()} />);

    expect(screen.getByText("지도 선택을 사용할 수 없습니다.")).toBeInTheDocument();
    expect(screen.getByText(/출발지와 목적지 장소 검색을 이용해 주세요/)).toBeInTheDocument();
  });

  it("reverse-geocodes a map click through the Service API and returns canonical PlaceRef", async () => {
    vi.stubEnv("KAKAO_JS_API_KEY", "browser-domain-key");
    class FakeLatLng implements KakaoLatLng {
      constructor(private readonly lat: number, private readonly lon: number) {}
      getLat() { return this.lat; }
      getLng() { return this.lon; }
    }
    class FakeMap {
      constructor(_element: HTMLElement, _options: { center: KakaoLatLng; level: number }) {}
      setCenter(_position: KakaoLatLng) {}
    }
    class FakeMarker {
      constructor(_options: { map: FakeMap; position: KakaoLatLng; draggable?: boolean }) {}
      setPosition(_position: KakaoLatLng) {}
    }
    class FakePolyline {
      constructor(_options: unknown) {}
    }
    const listeners: Array<{ target: object; event: string; handler: (event: { latLng?: KakaoLatLng }) => void }> = [];
    const maps = {
      load: (callback: () => void) => callback(),
      LatLng: FakeLatLng,
      Map: FakeMap,
      Marker: FakeMarker,
      Polyline: FakePolyline,
      event: {
        addListener: (target: object, event: string, handler: (event: { latLng?: KakaoLatLng }) => void) => listeners.push({ target, event, handler }),
        removeListener: (target: object, event: string, handler: (event: { latLng?: KakaoLatLng }) => void) => {
          const index = listeners.findIndex((item) => item.target === target && item.event === event && item.handler === handler);
          if (index >= 0) listeners.splice(index, 1);
        },
      },
    } satisfies KakaoMaps;
    window.kakao = { maps };
    const selected = { displayName: "선택 주소", coordinate: { lon: 127.25, lat: 37.45 }, provider: "KAKAO_LOCAL" };
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => new Response(JSON.stringify(selected), {
      status: 200,
      headers: { "content-type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const onPlaceSelected = vi.fn();
    const user = userEvent.setup();
    render(<MapCoordinatePicker origin={origin} destination={destination} onPlaceSelected={onPlaceSelected} />);

    await waitFor(() => expect(listeners.some((listener) => listener.event === "click")).toBe(true));
    const click = listeners.find((listener) => listener.event === "click");
    if (click === undefined) throw new Error("Expected Kakao map click listener");
    act(() => click.handler({ latLng: new FakeLatLng(37.45, 127.25) }));
    expect(onPlaceSelected).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "이 위치 선택" }));

    await waitFor(() => expect(onPlaceSelected).toHaveBeenCalledWith("ORIGIN", selected));
    const request = fetchMock.mock.calls[0]?.[0];
    if (!(request instanceof Request)) throw new Error("Expected generated client Request");
    expect(request.url).toContain("/api/v1/places/reverse-geocode");
    expect(request.url).toContain("lon=127.25");
    expect(request.url).toContain("lat=37.45");
  });
});
