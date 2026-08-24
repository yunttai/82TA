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
  it("keeps expired response content and prioritizes board, alight, and next-leg cues", async () => {
    const user = userEvent.setup();
    render(<ResultPanel phase="EXPIRED" response={expiredResponse} problem={null} />);

    expect(screen.getByText("이전 검색 결과를 보고 있어요.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "경로 상세" })).toBeVisible();
    expect(screen.queryByText("어디서 타고, 어디서 갈아타는지")).not.toBeInTheDocument();
    expect(screen.getByText("승차 정류장에서 버스 승차")).toBeVisible();
    expect(screen.getByText("환승 정류장에서 하차")).toBeVisible();
    expect(screen.getByText("다음 · 도착지까지 도보")).toBeVisible();
    expect(screen.getByText("도착지까지 걸어서 이동")).toBeVisible();
    expect(screen.queryByText(/제공사 추정 · 신뢰도 정보 없음/)).not.toBeInTheDocument();
    expect(screen.queryByText(/P50|P90|ETA|Routing 응답|대용값/)).not.toBeInTheDocument();
    expect(screen.getByText(/이전 검색 결과에는 의견을 남길 수 없습니다/)).toBeInTheDocument();

    const walkStep = screen.getByRole("button", { name: /2 · 도보.*도착지까지 걸어서 이동/ });
    expect(walkStep).toHaveAttribute("aria-pressed", "false");
    await user.click(walkStep);
    expect(walkStep).toHaveAttribute("aria-pressed", "true");
  });
});
