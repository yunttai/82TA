import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { KakaoLatLng, KakaoMaps } from "../map/kakaoMaps";
import type { RouteCandidate } from "../../shared/api/publicService";
import { RouteMap } from "./RouteMap";

function routeWithGeometry(value: unknown, encoding: "POLYLINE" | "GEOJSON" = "POLYLINE"): RouteCandidate {
  const confidence = { score: 0.9, grade: "HIGH" } as const;
  return {
    routeId: "polyline-route",
    pattern: "TRANSIT_ONLY",
    totalDuration: { p50Seconds: 600, p90Seconds: 800, confidence, origin: "PROVIDER_ESTIMATE" },
    taxiCost: { currency: "KRW", lower: 0, expected: 0, upper: 0, origin: "PROVIDER_ESTIMATE" },
    totalFareExpected: 1500,
    walkSeconds: 0,
    transferCount: 0,
    taxiLegCount: 0,
    reliabilityScore: 0.9,
    legs: [{
      legId: "polyline-leg",
      sequence: 1,
      mode: "BUS",
      from: { name: "A", coordinate: { lon: -120.2, lat: 38.5 } },
      to: { name: "B", coordinate: { lon: -126.453, lat: 43.252 } },
      duration: { p50Seconds: 600, p90Seconds: 800, confidence, origin: "PROVIDER_ESTIMATE" },
      distanceMeters: 1000,
      fare: { currency: "KRW", lower: 1500, expected: 1500, upper: 1500, origin: "PROVIDER_ESTIMATE" },
      geometry: { encoding, value },
      provenance: [],
    }],
    reasonCodes: [],
    warningCodes: [],
  };
}

afterEach(() => {
  delete window.kakao;
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("RouteMap canonical POLYLINE rendering", () => {
  it("renders a valid decoded line through the Kakao browser SDK", async () => {
    vi.stubEnv("VITE_KAKAO_MAP_APP_KEY", "browser-key");
    class FakeLatLng implements KakaoLatLng {
      constructor(private readonly lat: number, private readonly lon: number) {}
      getLat() { return this.lat; }
      getLng() { return this.lon; }
    }
    class FakeMap { setCenter(_position: KakaoLatLng) {} }
    class FakeMarker { setPosition(_position: KakaoLatLng) {} }
    const polylinePaths: KakaoLatLng[][] = [];
    class FakePolyline {
      constructor(options: { path: KakaoLatLng[] }) { polylinePaths.push(options.path); }
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

    render(<RouteMap route={routeWithGeometry("_p~iF~ps|U_ulLnnqC_mqNvxq`@")} />);

    await waitFor(() => expect(polylinePaths).toHaveLength(1));
    expect(polylinePaths[0]).toHaveLength(3);
    expect(screen.queryByText(/POLYLINE 구간은/)).not.toBeInTheDocument();
  });

  it("discloses malformed geometry without drawing a fake line", () => {
    render(<RouteMap route={routeWithGeometry("?????")} />);
    expect(screen.getByText(/형식 또는 좌표가 올바르지 않아 표시하지 않았습니다/)).toBeInTheDocument();
  });

  it("discloses oversized geometry without decoding it", () => {
    render(<RouteMap route={routeWithGeometry("a".repeat(100_001))} />);
    expect(screen.getByText(/안전한 표시 한도를 넘어 표시하지 않았습니다/)).toBeInTheDocument();
  });

  it("discloses malformed and oversized GEOJSON without iterating into a fake line", () => {
    const { rerender } = render(<RouteMap route={routeWithGeometry({ type: "LineString", coordinates: [[127.1, 37.3], [Infinity, 37.4]] }, "GEOJSON")} />);
    expect(screen.getByText(/GEOJSON 구간은 형식 또는 좌표가 올바르지 않아 표시하지 않았습니다/)).toBeInTheDocument();

    rerender(<RouteMap route={routeWithGeometry({ type: "LineString", coordinates: Array.from({ length: 10_001 }, () => [127.1, 37.3]) }, "GEOJSON")} />);
    expect(screen.getByText(/GEOJSON 구간은 안전한 표시 한도를 넘어 표시하지 않았습니다/)).toBeInTheDocument();
  });
});
