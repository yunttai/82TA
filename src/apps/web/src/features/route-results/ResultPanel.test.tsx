import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { PublicRouteSearchResponse, RouteCandidate } from "../../shared/api/publicService";
import { ResultPanel } from "./ResultPanel";

const confidence = { score: 0, grade: "UNKNOWN" } as const;
const timeEstimate = {
  p50Seconds: 600,
  p90Seconds: 780,
  confidence,
  origin: "PROVIDER_ESTIMATE",
} as const;
const noFare = { currency: "KRW", lower: 0, expected: 0, upper: 0, origin: "PROVIDER_ESTIMATE" } as const;
const routineProvenance = {
  provider: "SANITIZED_PROVIDER",
  origin: "PROVIDER_ESTIMATE",
  receivedAt: "2026-08-24T09:00:00+09:00",
  confidence,
  fallbackLevel: 0,
} as const;

const route = {
  routeId: "route-timeline",
  pattern: "TRANSIT_ONLY",
  totalDuration: { ...timeEstimate, p50Seconds: 720, p90Seconds: 900 },
  taxiCost: noFare,
  totalFareExpected: 1_500,
  walkSeconds: 120,
  transferCount: 1,
  taxiLegCount: 0,
  reliabilityScore: 0,
  legs: [
    {
      legId: "bus-leg",
      sequence: 0,
      mode: "BUS",
      from: { name: "승차 정류장", coordinate: { lon: 127.1, lat: 37.3 } },
      to: { name: "환승 정류장", coordinate: { lon: 127.2, lat: 37.4 } },
      duration: timeEstimate,
      distanceMeters: 8_000,
      fare: { ...noFare, lower: 1_500, expected: 1_500, upper: 1_500 },
      geometry: { encoding: "NONE" },
      provenance: [routineProvenance],
    },
    {
      legId: "walk-leg",
      sequence: 1,
      mode: "WALK",
      from: { name: "환승 정류장", coordinate: { lon: 127.2, lat: 37.4 } },
      to: { name: "도착지", coordinate: { lon: 127.21, lat: 37.41 } },
      duration: { ...timeEstimate, p50Seconds: 120, p90Seconds: 120 },
      distanceMeters: 180,
      fare: noFare,
      geometry: { encoding: "NONE" },
      provenance: [routineProvenance],
    },
  ],
  reasonCodes: [],
  warningCodes: [],
  provenance: [routineProvenance],
} satisfies RouteCandidate;

const expiredResponse = {
  contractVersion: "1.4.0",
  searchId: "search-expired",
  status: "EXPIRED",
  generatedAt: "2026-08-24T09:00:00+09:00",
  expiresAt: "2026-08-24T09:02:00+09:00",
  recommendations: { fastest: route, stable: route, efficient: null, publicTransitOnly: null },
  warnings: [],
  support: { features: {}, busIntelligenceCoverage: "UNKNOWN", degraded: [] },
} satisfies PublicRouteSearchResponse;

describe("ResultPanel journey guidance", () => {
  it("uses customer-safe zero-wait copy and displays the total fare above the taxi upper estimate", () => {
    const subwayRoute: RouteCandidate = {
      ...route,
      routeId: "zero-wait-subway",
      taxiCost: { ...noFare, lower: 10_000, expected: 11_000, upper: 12_000 },
      totalFareExpected: 12_000,
      legs: [{
        ...route.legs[0]!,
        legId: "subway-zero-wait",
        mode: "SUBWAY",
        duration: timeEstimate,
        waitDuration: { ...timeEstimate, p50Seconds: 0, p90Seconds: 0 },
        travelDuration: timeEstimate,
      }],
    };
    const beforeRender = structuredClone(subwayRoute);
    const response: PublicRouteSearchResponse = {
      ...expiredResponse,
      status: "COMPLETE",
      recommendations: { fastest: subwayRoute, stable: subwayRoute, efficient: null, publicTransitOnly: null },
    };

    const { container } = render(<ResultPanel phase="COMPLETE" response={response} problem={null} />);

    expect(screen.getByText("곧 도착")).toBeVisible();
    const customerCopy = [
      container.textContent,
      ...Array.from(container.querySelectorAll("[title], [aria-label]")).flatMap((element) => [
        element.getAttribute("title"),
        element.getAttribute("aria-label"),
      ]),
    ].filter((value): value is string => value !== null).join(" ");
    expect(customerCopy).not.toContain("지하철 대기 0분");
    expect(screen.getByText("택시비 최대 예상").nextElementSibling).toHaveTextContent("12,000원");
    expect(screen.getByText("전체 예상 요금").nextElementSibling).toHaveTextContent("15,000원");
    expect(subwayRoute).toEqual(beforeRender);
  });

  it("keeps expired response content and prioritizes board, alight, and next-leg cues", async () => {
    const user = userEvent.setup();
    render(<ResultPanel phase="EXPIRED" response={expiredResponse} problem={null} />);

    expect(screen.getByText("이전 검색 결과를 보고 있어요.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "경로 상세" })).toBeVisible();
    expect(screen.queryByText("어디서 타고, 어디서 갈아타는지")).not.toBeInTheDocument();
    expect(screen.getByText("승차 정류장에서 버스 승차")).toBeVisible();
    expect(screen.getByText("환승 정류장에서 하차")).toBeVisible();
    expect(screen.getByText("도착지까지 걸어서 이동")).toBeVisible();
    expect(screen.queryByText(/다음 ·/)).not.toBeInTheDocument();
    expect(screen.queryByText("도착지 도착")).not.toBeInTheDocument();
    expect(screen.queryByText(/제공사 추정 · 신뢰도 정보 없음/)).not.toBeInTheDocument();
    expect(screen.queryByText(/P50|P90|ETA|Routing 응답|대용값/)).not.toBeInTheDocument();
    expect(screen.getByText(/이전 검색 결과에는 의견을 남길 수 없습니다/)).toBeInTheDocument();

    const walkStep = screen.getByRole("button", { name: /2 · 도보.*도착지까지 걸어서 이동/ });
    expect(walkStep).toHaveAttribute("aria-pressed", "false");
    await user.click(walkStep);
    expect(walkStep).toHaveAttribute("aria-pressed", "true");
  });

  it("hides provider placeholders and combines repeated same-station walk connectors", () => {
    const rawRoute: RouteCandidate = {
      ...route,
      routeId: "raw-provider-route",
      pattern: "TAXI_TRANSIT",
      legs: [
        {
          ...route.legs[0]!,
          legId: "taxi-access",
          sequence: 0,
          mode: "TAXI",
          from: { name: "Origin", coordinate: { lon: 127.1, lat: 37.3 } },
          to: { name: "Destination", coordinate: { lon: 127.11, lat: 37.31 } },
          transit: null,
        },
        {
          ...route.legs[0]!,
          legId: "subway-one",
          sequence: 1,
          mode: "SUBWAY",
          from: { name: "판교(판교테크노밸리)", coordinate: { lon: 127.11, lat: 37.31 } },
          to: { name: "논현", coordinate: { lon: 127.12, lat: 37.32 } },
          transit: { routeLabel: "신분당선", direction: "Kakao Transit Destination" } as unknown as NonNullable<RouteCandidate["legs"][number]["transit"]>,
        },
        ...[0, 121, 1].map((seconds, index) => ({
          ...route.legs[1]!,
          legId: `same-station-walk-${index}`,
          sequence: index + 2,
          from: { name: "논현", coordinate: { lon: 127.12, lat: 37.32 } },
          to: { name: "논현", coordinate: { lon: 127.12, lat: 37.32 } },
          duration: { ...timeEstimate, p50Seconds: seconds, p90Seconds: seconds },
          distanceMeters: index === 1 ? 100 : index,
        })),
        {
          ...route.legs[0]!,
          legId: "subway-two",
          sequence: 5,
          mode: "SUBWAY",
          from: { name: "논현", coordinate: { lon: 127.12, lat: 37.32 } },
          to: { name: "어린이대공원(세종대)", coordinate: { lon: 127.13, lat: 37.33 } },
          transit: { routeLabel: "7호선", direction: null } as unknown as NonNullable<RouteCandidate["legs"][number]["transit"]>,
        },
        {
          ...route.legs[1]!,
          legId: "final-walk",
          sequence: 6,
          from: { name: "어린이대공원(세종대)", coordinate: { lon: 127.13, lat: 37.33 } },
          to: { name: "Kakao transit destination", coordinate: { lon: 127.14, lat: 37.34 } },
        },
      ],
    };
    const beforeRender = structuredClone(rawRoute);
    const response: PublicRouteSearchResponse = {
      ...expiredResponse,
      status: "COMPLETE",
      recommendations: { fastest: rawRoute, stable: rawRoute, efficient: null, publicTransitOnly: null },
    };

    const { container } = render(<ResultPanel phase="COMPLETE" response={response} problem={null} />);

    const customerCopy = [
      container.textContent,
      ...Array.from(container.querySelectorAll("[title], [aria-label]")).flatMap((element) => [
        element.getAttribute("title"),
        element.getAttribute("aria-label"),
      ]),
    ].filter((value): value is string => value !== null).join(" ");
    expect(customerCopy).not.toMatch(/Origin|Destination|Kakao\s+Transit|Sanitized|Fixture/i);
    expect(screen.getByText("출발지")).toBeVisible();
    expect(screen.getByText("도착지")).toBeVisible();
    expect(screen.getAllByText("논현에서 환승 통로로 이동")).toHaveLength(1);
    expect(screen.getByText("5단계")).toBeVisible();
    expect(screen.getByText("지하철 신분당선")).toBeVisible();
    expect(screen.queryByText(/다음 ·/)).not.toBeInTheDocument();
    expect(rawRoute).toEqual(beforeRender);
  });
});
