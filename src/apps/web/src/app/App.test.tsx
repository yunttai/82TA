import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import canonicalBikeOptions from "../../../../contracts/openapi/examples/public-bike-options-response.json";
import canonicalResponse from "../../../../contracts/openapi/examples/public-route-search-response.json";
import { ResultPanel } from "../features/route-results/ResultPanel";
import type { PublicProblem, PublicRouteSearchRequest, PublicRouteSearchResponse, RouteCandidate } from "../shared/api/publicService";
import { clearSessionMemory, currentGuestToken, rememberGuestSession } from "../shared/session/sessionMemory";
import { App } from "./App";

const guestCredential = {
  guestToken: "guest_test_0123456789abcdef0123456789abcdef",
  expiresAt: "2099-08-24T07:40:00+09:00",
};

function sessionResponse(input: RequestInfo | URL): Response | null {
  const request = input instanceof Request ? input : new Request(input);
  const path = new URL(request.url).pathname;
  if (path === "/api/v1/guest-sessions" && request.method === "POST") {
    return new Response(JSON.stringify(guestCredential), { status: 201, headers: { "content-type": "application/json" } });
  }
  if (path === "/api/v1/session" && request.method === "GET") {
    const token = request.headers.get("X-Guest-Token");
    return token === guestCredential.guestToken
      ? new Response(JSON.stringify({ subjectType: "GUEST", authenticated: false, expiresAt: guestCredential.expiresAt }), { status: 200, headers: { "content-type": "application/json" } })
      : new Response(JSON.stringify({}), { status: 401, headers: { "content-type": "application/problem+json" } });
  }
  return null;
}

function placeSuggestionResponse(input: RequestInfo | URL): Response | null {
  const request = input instanceof Request ? input : new Request(input);
  const url = new URL(request.url);
  if (url.pathname !== "/api/v1/places/suggest") return null;
  const origin = url.searchParams.get("query")?.includes("명지") === true;
  return new Response(JSON.stringify({
    items: [{
      displayName: origin ? "명지대학교 자연캠퍼스" : "판교역",
      coordinate: origin ? { lon: 127.187456, lat: 37.222345 } : { lon: 127.111159, lat: 37.394761 },
      provider: "KAKAO_LOCAL",
      providerPlaceId: origin ? "place-origin" : "place-destination",
      regionCode: "41135",
    }],
  }), { status: 200, headers: { "content-type": "application/json" } });
}

async function selectDefaultPlaces(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByRole("combobox", { name: "출발지" }), "명지");
  await user.type(screen.getByRole("combobox", { name: "목적지" }), "판교");
  await user.click(await screen.findByRole("option", { name: "명지대학교 자연캠퍼스" }));
  await user.click(await screen.findByRole("option", { name: "판교역" }));
}

function responseBody(status: "COMPLETE" | "PARTIAL" = "PARTIAL", warnings = canonicalResponse.warnings): string {
  return JSON.stringify({
    ...canonicalResponse,
    status,
    expiresAt: "2099-08-23T07:42:05.421+09:00",
    warnings,
  });
}

function successfulFetch(body = responseBody()) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const session = sessionResponse(input);
    if (session !== null) return session;
    const placeSuggestion = placeSuggestionResponse(input);
    if (placeSuggestion !== null) return placeSuggestion;
    const url = input instanceof Request ? input.url : input.toString();
    if (url.endsWith("/api/v1/health")) {
      return new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (url.endsWith("/api/v1/support/capabilities")) {
      return new Response(JSON.stringify({
        features: { taxiBridge: true, busSeatRisk: true },
        busIntelligenceCoverage: "PARTIAL",
        degraded: [],
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (new URL(url).pathname === "/api/v1/bike-options") {
      return new Response(JSON.stringify(canonicalBikeOptions), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(body, {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
}

function busResponse(mappingGrade: "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN"): PublicRouteSearchResponse {
  const confidence = { score: 0.9, grade: "HIGH" } as const;
  const route = {
    routeId: `bus-route-${mappingGrade.toLowerCase()}`,
    pattern: "TRANSIT_ONLY",
    totalDuration: { p50Seconds: 1200, p90Seconds: 1500, confidence, origin: "PROVIDER_ESTIMATE" },
    taxiCost: { currency: "KRW", lower: 0, expected: 0, upper: 0, origin: "PROVIDER_ESTIMATE" },
    totalFareExpected: 2800,
    walkSeconds: 120,
    transferCount: 0,
    taxiLegCount: 0,
    reliabilityScore: 0.9,
    legs: [{
      legId: "bus-leg-1",
      sequence: 1,
      mode: "BUS",
      from: { name: "승차 정류장", coordinate: { lon: 127.1, lat: 37.3 } },
      to: { name: "하차 정류장", coordinate: { lon: 127.2, lat: 37.4 } },
      duration: { p50Seconds: 900, p90Seconds: 1100, confidence, origin: "PROVIDER_ESTIMATE" },
      waitDuration: { p50Seconds: 180, p90Seconds: 360, confidence, origin: "PROVIDER_ESTIMATE" },
      travelDuration: { p50Seconds: 720, p90Seconds: 740, confidence, origin: "PROVIDER_ESTIMATE" },
      distanceMeters: 8000,
      fare: { currency: "KRW", lower: 2800, expected: 2800, upper: 2800, origin: "PROVIDER_ESTIMATE" },
      geometry: { encoding: "NONE" },
      transit: { routeLabel: "9241", routeType: "SEAT_BUS", direction: "판교 방면" } as unknown as NonNullable<RouteCandidate["legs"][number]["transit"]>,
      busIntelligence: {
        mapping: { grade: mappingGrade, score: mappingGrade === "HIGH" ? 0.99 : 0.8 },
        candidateVehicles: [{
          vehicleRef: "vehicle-sensitive-ref",
          eta: { p50Seconds: 180, p90Seconds: 300, confidence, origin: "OBSERVED" },
          remainSeatObserved: 0,
          seatRiskAtBoarding: { noSeatProbability: 0.9, lowSeat2Probability: 0.95, modelVersion: "test-model" },
          boardabilityProxy: 0.1,
        }],
        expectedWaitSeconds: 180,
        p90WaitSeconds: 360,
        coverage: "LIVE",
        warnings: ["BOARDABILITY_IS_PROXY"],
      },
      provenance: [],
    }],
    reasonCodes: [],
    warningCodes: [],
  } satisfies RouteCandidate;

  return {
    contractVersion: "1.1.0",
    searchId: `search-${mappingGrade.toLowerCase()}`,
    status: "COMPLETE",
    generatedAt: "2026-08-23T00:00:00+09:00",
    expiresAt: "2099-08-23T00:00:00+09:00",
    recommendations: { fastest: route, stable: null, efficient: null, publicTransitOnly: null },
    warnings: [],
    support: { features: { busSeatRisk: true, busEtaModel: true }, busIntelligenceCoverage: "LIVE", degraded: [] },
  };
}

afterEach(() => {
  document.cookie = "csrftoken=; Max-Age=0; Path=/";
  clearSessionMemory();
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("map-first home", () => {
  it("opens with the branded map surface and exactly five primary destinations", async () => {
    vi.stubGlobal("fetch", successfulFetch());
    const user = userEvent.setup();
    render(<App />);

    expect(screen.queryByRole("heading", { name: /예산은 지키고.*도착은 빠르게/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /길찾기 카드/ })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: /경기 남부와 서울 이동 지도/ })).toBeInTheDocument();
    const mobileNavigation = screen.getByRole("navigation", { name: "모바일 주요 메뉴" });
    expect(mobileNavigation.querySelectorAll("a")).toHaveLength(5);
    expect(screen.getAllByRole("link", { name: "홈" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "길찾기" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "기록" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "즐겨찾기" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "내 정보" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "홈" })[1]).toHaveAttribute("aria-current", "page");

    await user.click(screen.getByRole("link", { name: /어디로 갈까요/ }));
    expect(window.location.pathname).toBe("/search");
    expect(screen.getByRole("heading", { name: "어디로 갈까요?" })).toBeInTheDocument();
  });

});

describe("route search vertical slice", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/search");
  });

  it("renders an app-like mobile shell with labelled icon navigation and progressive map controls", () => {
    vi.stubGlobal("fetch", successfulFetch());
    render(<App />);

    expect(screen.getByRole("heading", { name: "어디로 갈까요?" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "모바일 주요 메뉴" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "길찾기" })).toHaveLength(2);
    const mapDetails = screen.getByText("지도에서 직접 위치 선택").closest("details");
    expect(mapDetails).not.toHaveAttribute("open");
    expect(screen.getByText("예산 안에서 더 빠르고 안정적인 이동을 찾아드려요.")).toBeInTheDocument();
    expect(screen.queryByText("택시 예산 안에서 더 빠르고 안정적인 이동을 찾아드려요.")).not.toBeInTheDocument();
  });

  it("starts with empty places and exposes only the two primary options", async () => {
    const fetchMock = successfulFetch();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);

    expect(screen.getByRole("combobox", { name: "출발지" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "목적지" })).toHaveValue("");
    expect(screen.getByText("예상 요금 상한")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /직접 입력/ })).toHaveValue("10000");
    expect(screen.getByRole("button", { name: "무관" })).toBeInTheDocument();
    expect(screen.queryByText("세부 조건")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "대중교통 사이 짧은 택시 이동 허용" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "검색 기록에 저장" })).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.queryByRole("textbox", { name: "출발 경도" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "출발 위도" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "도착 경도" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "도착 위도" })).not.toBeInTheDocument();
    const selectedPreset = screen.getByRole("button", { name: "1만원" });
    expect(selectedPreset).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("textbox", { name: /직접 입력/ }));
    expect(selectedPreset).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: "무관" }));
    expect(screen.getByRole("textbox", { name: /직접 입력/ })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: /직접 입력/ })).toHaveAttribute("placeholder", "무관 선택됨");
  });

  it("posts only to the public route-search endpoint and renders the partial canonical recommendations", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    const fetchMock = successfulFetch();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await selectDefaultPlaces(user);
    await user.click(screen.getByRole("button", { name: "5천원" }));
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findAllByText("일부 정보 제한")).toHaveLength(1);
    expect(screen.getByText("일부 정보 없이 계산한 결과입니다.")).toBeInTheDocument();
    expect(screen.queryByText("추천 경로 없음")).not.toBeInTheDocument();
    for (const label of ["가장 빠른 경로", "가장 안정적인 경로", "비용 효율 경로", "대중교통만 이용"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(document.querySelectorAll(".route-card")).toHaveLength(1);
    expect(screen.getAllByText("버스 실시간 정보를 사용할 수 없습니다.")).toHaveLength(2);
    const bikePanel = await screen.findByRole("region", { name: "따릉이로 이동하기" });
    expect(within(bikePanel).getByText("약 33분")).toBeVisible();
    expect(within(bikePanel).getByText("직선거리·시속 15km 단순 예상", { exact: false })).toBeVisible();
    expect(within(bikePanel).getByText("실시간 대여 가능 수량은 따릉이 앱에서 확인", { exact: false })).toBeVisible();

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => (input instanceof Request ? input.url : input.toString()).endsWith("/api/v1/route-searches"))).toBe(true));
    const healthCall = fetchMock.mock.calls.find(([input]) => (input instanceof Request ? input.url : input.toString()).endsWith("/api/v1/health"));
    const routeCall = fetchMock.mock.calls.find(([input]) => (input instanceof Request ? input.url : input.toString()).endsWith("/api/v1/route-searches"));
    if (healthCall === undefined || routeCall === undefined) throw new Error("Expected CSRF bootstrap and route calls");

    const healthRequest = healthCall[0] instanceof Request ? healthCall[0].clone() : new Request(healthCall[0]);
    expect(healthRequest.url).toMatch(/\/api\/v1\/health$/);
    expect(healthRequest.method).toBe("GET");
    expect(healthRequest.credentials).toBe("same-origin");

    const routeRequest = routeCall[0] instanceof Request ? routeCall[0].clone() : new Request(routeCall[0]);
    expect(routeRequest.url).toMatch(/\/api\/v1\/route-searches$/);
    expect(routeRequest.method).toBe("POST");
    expect(routeRequest.credentials).toBe("same-origin");
    expect(routeRequest.headers.get("X-CSRFToken")).toBe("csrf-test-token");
    expect(routeRequest.headers.get("Idempotency-Key")).toBeTruthy();
    expect(currentGuestToken()).toBe(guestCredential.guestToken);
    const body = await routeRequest.text();
    expect(body).toContain('"maxAmount":2000');
    expect(body).toContain('"strict":true');
    expect(body).toContain('"maxWalkSeconds":7200');
    expect(body).toContain('"maxTransfers":8');
    expect(body).toContain('"maxTaxiLegs":3');
    expect(body).toContain('"requestedRecommendations":["FASTEST","STABLE","EFFICIENT","PUBLIC_TRANSIT_ONLY"]');

    const bikeCall = fetchMock.mock.calls.find(([input]) => new URL(input instanceof Request ? input.url : input.toString()).pathname === "/api/v1/bike-options");
    if (bikeCall === undefined) throw new Error("Expected supplemental bike-options request");
    const bikeRequest = bikeCall[0] instanceof Request ? bikeCall[0] : new Request(bikeCall[0]);
    const bikeUrl = new URL(bikeRequest.url);
    expect(Object.fromEntries(bikeUrl.searchParams)).toEqual({
      originLon: "127.187456",
      originLat: "37.222345",
      destinationLon: "127.111159",
      destinationLat: "37.394761",
    });
  });

  it("preserves place swap, scheduled departure, budget, and hidden preference defaults", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    const fetchMock = successfulFetch();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await selectDefaultPlaces(user);
    await user.click(screen.getByRole("button", { name: "출발지와 목적지 바꾸기" }));
    await user.click(screen.getByRole("button", { name: "무관" }));
    expect(screen.getByRole("textbox", { name: /직접 입력/ })).toHaveValue("");
    await user.click(screen.getByRole("radio", { name: "지정 시각 출발" }));
    await user.clear(screen.getByLabelText("지정 출발 시각 · 한국 시간"));
    await user.type(screen.getByLabelText("지정 출발 시각 · 한국 시간"), "2030-01-02T10:30");
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findAllByText("일부 정보 제한")).toHaveLength(1);
    const routeCall = fetchMock.mock.calls.find(([input]) => (input instanceof Request ? input.url : input.toString()).endsWith("/api/v1/route-searches"));
    if (routeCall === undefined) throw new Error("Expected route request");
    const request = routeCall[0] instanceof Request ? routeCall[0].clone() : new Request(routeCall[0]);
    const body = await request.json() as PublicRouteSearchRequest;
    expect(body.origin.displayName).toBe("판교역");
    expect(body.destination.displayName).toBe("명지대학교 자연캠퍼스");
    expect(body.taxiBudget.maxAmount).toBe(500_000);
    expect(body.departure.type).toBe("DEPART_AT");
    expect(body.departure.time).toBe("2030-01-02T01:30:00.000Z");
    expect(body.arrivalDeadline).toBeNull();
    expect(body.preferences.maxWalkSeconds).toBe(7_200);
    expect(body.preferences.maxTransfers).toBe(8);
    expect(body.preferences.maxTaxiLegs).toBe(3);
  });

  it("keeps an offline draft but blocks route-search submission", async () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    const fetchMock = successfulFetch();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    const submit = screen.getByRole("button", { name: "연결 후 경로 검색 가능" });
    expect(submit).toBeDisabled();
    expect(screen.getByText(/연결 후 입력을 확인하고 직접 검색/)).toBeInTheDocument();
    await user.click(submit);
    expect(fetchMock.mock.calls.some(([input]) => (input instanceof Request ? input.url : input.toString()).endsWith("/api/v1/route-searches"))).toBe(false);
  });

  it("keeps the CSRF token out of storage and logs", async () => {
    document.cookie = "csrftoken=ephemeral-csrf-token; Path=/; SameSite=Lax";
    const storageSpy = vi.spyOn(Storage.prototype, "setItem");
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const infoSpy = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", successfulFetch());
    const user = userEvent.setup();

    render(<App />);
    await selectDefaultPlaces(user);
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findAllByText("일부 정보 제한")).toHaveLength(1);
    expect(storageSpy).not.toHaveBeenCalled();
    expect(logSpy).not.toHaveBeenCalled();
    expect(infoSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("keeps the guest credential in memory across internal SPA navigation", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    const storageSpy = vi.spyOn(Storage.prototype, "setItem");
    vi.stubGlobal("fetch", successfulFetch());
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole("link", { name: "계정" }));
    await user.click(await screen.findByRole("button", { name: "게스트 세션 시작" }));
    expect(await screen.findByText(/게스트 ·/)).toBeInTheDocument();
    expect(currentGuestToken()).toBe(guestCredential.guestToken);

    await user.click(screen.getByRole("link", { name: "지원 범위" }));
    expect(window.location.pathname).toBe("/support");
    expect(screen.getByRole("main")).toHaveFocus();
    expect(currentGuestToken()).toBe(guestCredential.guestToken);
    expect(storageSpy).not.toHaveBeenCalled();
  });

  it("sends the memory-only guest credential when reopening an owned search", async () => {
    rememberGuestSession(guestCredential.guestToken, {
      subjectType: "GUEST",
      authenticated: false,
      expiresAt: guestCredential.expiresAt,
    });
    window.history.replaceState(null, "", "/searches/search-owned");
    const fetchMock = successfulFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await screen.findByText("일부 정보 없이 계산한 결과입니다.");

    const ownedCall = fetchMock.mock.calls.find(([input]) => (input instanceof Request ? input.url : input.toString()).endsWith("/api/v1/route-searches/search-owned"));
    if (ownedCall === undefined) throw new Error("Expected owned search request");
    const request = ownedCall[0] instanceof Request ? ownedCall[0] : new Request(ownedCall[0]);
    expect(request.headers.get("X-Guest-Token")).toBe(guestCredential.guestToken);
  });

  it("applies the visible authenticated budget preference while advanced preferences stay off the search form", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(input);
      const path = new URL(request.url).pathname;
      if (path === "/api/v1/session") {
        return new Response(JSON.stringify({ subjectType: "USER", authenticated: true, expiresAt: guestCredential.expiresAt }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (path === "/api/v1/me/preferences") {
        return new Response(JSON.stringify({
          defaultTaxiBudget: 20_000,
          maxWalkSeconds: 1_800,
          maxTransfers: 6,
          maxTaxiLegs: 1,
          optimizationProfile: "STABLE",
          accessibility: { avoidStairs: true, wheelchair: true },
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (path === "/api/v1/support/capabilities") {
        return new Response(JSON.stringify({ features: {}, degraded: [] }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response("{}", { status: 404, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await waitFor(() => expect(screen.getByRole("textbox", { name: /직접 입력/ })).toHaveValue("23000"));
    expect(screen.queryByText("최대 도보")).not.toBeInTheDocument();
    expect(screen.queryByText("최대 환승")).not.toBeInTheDocument();
    expect(screen.queryByText("추천 기준")).not.toBeInTheDocument();
  });

  it("retries an uncertain network result with the exact same body and idempotency key", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    const routeRequests: Request[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const session = sessionResponse(input);
      if (session !== null) return session;
      const placeSuggestion = placeSuggestionResponse(input);
      if (placeSuggestion !== null) return placeSuggestion;
      const request = input instanceof Request ? input : new Request(input);
      if (request.url.endsWith("/api/v1/support/capabilities")) {
        return new Response(JSON.stringify({ features: {}, degraded: [] }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (request.url.endsWith("/api/v1/health")) {
        return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (!request.url.endsWith("/api/v1/route-searches")) return new Response("{}", { status: 404, headers: { "content-type": "application/json" } });
      routeRequests.push(request.clone());
      if (routeRequests.length === 1) throw new TypeError("connection lost after submit");
      return new Response(responseBody(), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await selectDefaultPlaces(user);
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));
    await user.click(await screen.findByRole("button", { name: "같은 요청으로 다시 확인" }));
    expect(await screen.findAllByText("일부 정보 제한")).toHaveLength(1);

    expect(routeRequests).toHaveLength(2);
    expect(routeRequests[0]?.headers.get("Idempotency-Key")).toBe(routeRequests[1]?.headers.get("Idempotency-Key"));
    expect(await routeRequests[0]?.text()).toBe(await routeRequests[1]?.text());
  });

  it("supports keyboard selection in Service place suggestions", async () => {
    vi.stubGlobal("fetch", successfulFetch());
    const user = userEvent.setup();
    render(<App />);

    const origin = screen.getByRole("combobox", { name: "출발지" });
    await user.clear(origin);
    await user.type(origin, "판교");
    expect(await screen.findByRole("option", { name: /판교역/ })).toBeInTheDocument();
    await user.keyboard("{ArrowDown}{Enter}");
    expect(origin).toHaveValue("판교역");
  });

  it("fails closed after bootstrap when the CSRF cookie is unavailable", async () => {
    const fetchMock = successfulFetch();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await selectDefaultPlaces(user);
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findByRole("heading", { name: "검색을 완료하지 못했습니다" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "교통 정보를 불러올 수 없습니다" })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => (input instanceof Request ? input.url : input.toString()).endsWith("/api/v1/health"))).toBe(true));
    const healthCall = fetchMock.mock.calls.find(([input]) => (input instanceof Request ? input.url : input.toString()).endsWith("/api/v1/health"));
    if (healthCall === undefined) throw new Error("Expected one CSRF bootstrap call");
    expect(new Request(healthCall[0]).url).toMatch(/\/api\/v1\/health$/);
  });

  it("reserves provider unavailable for an explicit 503 response", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const session = sessionResponse(input);
      if (session !== null) return session;
      const placeSuggestion = placeSuggestionResponse(input);
      if (placeSuggestion !== null) return placeSuggestion;
      const url = input instanceof Request ? input.url : input.toString();
      if (url.endsWith("/api/v1/support/capabilities")) {
        return new Response(JSON.stringify({ features: {}, degraded: [] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/api/v1/health")) {
        return new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify({
        type: "about:blank",
        title: "Transit provider unavailable",
        status: 503,
        code: "TRANSIT_PROVIDER_UNAVAILABLE",
        retryable: true,
        correlationId: "test-correlation",
        violations: [],
        safeContext: {},
      }), { status: 503, headers: { "content-type": "application/problem+json" } });
    }));
    const user = userEvent.setup();

    render(<App />);
    await selectDefaultPlaces(user);
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findByRole("heading", { name: "교통 정보를 불러올 수 없습니다" })).toBeInTheDocument();
  });

  it("uses a generic safe label for an unknown warning code", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    vi.stubGlobal("fetch", successfulFetch(responseBody("COMPLETE", ["NEW_WARNING_CODE"])));
    const user = userEvent.setup();

    render(<App />);
    await selectDefaultPlaces(user);
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findByText("일부 정보를 확인할 수 없습니다.")).toBeInTheDocument();
    expect(screen.queryByText("NEW_WARNING_CODE")).not.toBeInTheDocument();
  });

  it("keeps a returned route snapshot visible when its freshness timestamp has passed", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    vi.stubGlobal("fetch", successfulFetch(JSON.stringify({
      ...canonicalResponse,
      status: "COMPLETE",
      expiresAt: "2000-01-01T00:00:00+09:00",
      warnings: [],
    })));
    const user = userEvent.setup();

    render(<App />);
    await selectDefaultPlaces(user);
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findByRole("button", { name: "조건 수정" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "이 결과는 만료되었습니다" })).not.toBeInTheDocument();
  });
});

describe("terminal route-search states", () => {
  const states: ReadonlyArray<readonly [PublicRouteSearchResponse["status"], string]> = [
    ["NO_FEASIBLE_ROUTE", "조건에 맞는 경로가 없습니다"],
    ["PROVIDER_UNAVAILABLE", "교통 정보를 불러올 수 없습니다"],
    ["EXPIRED", "이 결과는 만료되었습니다"],
    ["FAILED", "검색을 완료하지 못했습니다"],
  ];

  it.each(states)("renders %s honestly", (phase, heading) => {
    render(<ResultPanel phase={phase} response={null} problem={null} />);
    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
  });

  it("uses safe problem copy without exposing internal code or correlation identifiers", () => {
    const problem = {
      type: "about:blank",
      title: "rate limited",
      status: 429,
      code: "RATE_LIMITED",
      detail: null,
      retryable: true,
      correlationId: "sensitive-correlation-reference",
      violations: [],
      safeContext: {},
    } satisfies PublicProblem;
    render(<ResultPanel phase="FAILED" response={null} problem={problem} />);
    expect(screen.getByText("요청이 많아 잠시 후 다시 시도해 주세요.")).toBeInTheDocument();
    expect(screen.queryByText(/RATE_LIMITED|sensitive-correlation-reference/)).not.toBeInTheDocument();
  });

  it("offers a fresh-start action instead of replaying an expired idempotency key", async () => {
    const restart = vi.fn();
    const retry = vi.fn();
    const user = userEvent.setup();
    render(<ResultPanel phase="EXPIRED" response={null} problem={null} onRetry={retry} onRestart={restart} />);

    expect(screen.queryByRole("button", { name: "같은 요청으로 다시 확인" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "입력 조건 다시 확인" }));
    expect(restart).toHaveBeenCalledOnce();
    expect(retry).not.toHaveBeenCalled();
  });

  it("keeps an expired response snapshot readable instead of replacing its route", () => {
    render(<ResultPanel phase="EXPIRED" response={busResponse("HIGH")} problem={null} />);

    expect(screen.getByText("이전 검색 결과를 보고 있어요.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "경로 상세" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "이 결과는 만료되었습니다" })).not.toBeInTheDocument();
    expect(screen.getByText(/이전 검색 결과에는 의견을 남길 수 없습니다/)).toBeInTheDocument();
  });
});

describe("Bus Intelligence mapping gate", () => {
  it("renders walk, each bus wait, each bus ride, Taxi wait, Taxi ride and final walk in order", () => {
    const response = busResponse("HIGH");
    const base = response.recommendations.fastest;
    if (base == null || base.legs[0] === undefined) throw new Error("Expected route");
    const template = base.legs[0];
    const multimodal: RouteCandidate = {
      ...base,
      pattern: "TRANSIT_TAXI",
      totalDuration: { ...base.totalDuration, p50Seconds: 3_660, p90Seconds: 4_620 },
      taxiCost: { currency: "KRW", lower: 4_000, expected: 5_000, upper: 6_000, origin: "PROVIDER_ESTIMATE" },
      totalFareExpected: 7_800,
      walkSeconds: 300,
      transferCount: 2,
      taxiLegCount: 1,
      legs: [
        {
          ...template,
          legId: "walk-leg",
          sequence: 0,
          mode: "WALK",
          to: { name: "판교제2테크노밸리 승차", coordinate: { lon: 127.11, lat: 37.31 } },
          duration: { ...template.duration, p50Seconds: 120, p90Seconds: 150 },
          waitDuration: { ...template.duration, p50Seconds: 0, p90Seconds: 0 },
          travelDuration: { ...template.duration, p50Seconds: 120, p90Seconds: 150 },
          distanceMeters: 124,
          fare: { currency: "KRW", lower: 0, expected: 0, upper: 0, origin: "PROVIDER_ESTIMATE" },
          transit: null,
          busIntelligence: null,
        },
        {
          ...template,
          legId: "bus-leg",
          sequence: 1,
          from: { name: "판교제2테크노밸리 승차", coordinate: { lon: 127.11, lat: 37.31 } },
          to: { name: "삼가역·두산위브 하차", coordinate: { lon: 127.18, lat: 37.24 } },
          duration: { ...template.duration, p50Seconds: 2_460, p90Seconds: 2_900 },
          waitDuration: { ...template.duration, p50Seconds: 300, p90Seconds: 500 },
          travelDuration: { ...template.duration, p50Seconds: 2_160, p90Seconds: 2_400 },
          transit: { routeLabel: "9241", routeType: "SEAT_BUS", direction: "용인 방면" } as unknown as NonNullable<RouteCandidate["legs"][number]["transit"]>,
          busIntelligence: null,
        },
        {
          ...template,
          legId: "second-bus-leg",
          sequence: 2,
          from: { name: "삼가역·두산위브 환승", coordinate: { lon: 127.18, lat: 37.24 } },
          to: { name: "목적지 인근 정류장", coordinate: { lon: 127.19, lat: 37.23 } },
          duration: { ...template.duration, p50Seconds: 600, p90Seconds: 800 },
          waitDuration: { ...template.duration, p50Seconds: 120, p90Seconds: 200 },
          travelDuration: { ...template.duration, p50Seconds: 480, p90Seconds: 600 },
          transit: { routeLabel: "5000", routeType: "SEAT_BUS", direction: "목적지 방면" } as unknown as NonNullable<RouteCandidate["legs"][number]["transit"]>,
          busIntelligence: null,
        },
        {
          ...template,
          legId: "taxi-leg",
          sequence: 3,
          mode: "TAXI",
          from: { name: "목적지 인근 정류장", coordinate: { lon: 127.19, lat: 37.23 } },
          to: { name: "목적지 앞", coordinate: { lon: 127.2, lat: 37.22 } },
          duration: { ...template.duration, p50Seconds: 300, p90Seconds: 550 },
          waitDuration: { ...template.duration, p50Seconds: 60, p90Seconds: 120 },
          travelDuration: { ...template.duration, p50Seconds: 240, p90Seconds: 430 },
          distanceMeters: 2_100,
          fare: { currency: "KRW", lower: 4_000, expected: 5_000, upper: 6_000, origin: "PROVIDER_ESTIMATE" },
          transit: null,
          busIntelligence: null,
        },
        {
          ...template,
          legId: "final-walk-leg",
          sequence: 4,
          mode: "WALK",
          from: { name: "목적지 앞", coordinate: { lon: 127.2, lat: 37.22 } },
          duration: { ...template.duration, p50Seconds: 180, p90Seconds: 220 },
          waitDuration: { ...template.duration, p50Seconds: 0, p90Seconds: 0 },
          travelDuration: { ...template.duration, p50Seconds: 180, p90Seconds: 220 },
          distanceMeters: 210,
          fare: { currency: "KRW", lower: 0, expected: 0, upper: 0, origin: "PROVIDER_ESTIMATE" },
          transit: null,
          busIntelligence: null,
        },
      ],
    };
    render(
      <ResultPanel
        phase="COMPLETE"
        response={{
          ...response,
          recommendations: {
            fastest: multimodal,
            stable: multimodal,
            efficient: multimodal,
            publicTransitOnly: null,
          },
        }}
        problem={null}
      />,
    );

    const summary = screen.getByRole("list", { name: "이동 구간 요약" });
    const items = within(summary).getAllByRole("listitem");
    expect(items).toHaveLength(8);
    expect(items[0]).toHaveTextContent(/도보.*2분/);
    expect(items[1]).toHaveTextContent(/버스 대기.*5분/);
    expect(items[2]).toHaveTextContent(/버스 9241번.*36분/);
    expect(items[3]).toHaveTextContent(/버스 대기.*2분/);
    expect(items[4]).toHaveTextContent(/버스 5000번.*8분/);
    expect(items[5]).toHaveTextContent(/택시 예상 대기.*1분/);
    expect(items[6]).toHaveTextContent(/택시.*4분/);
    expect(items[7]).toHaveTextContent(/도보.*3분/);
    expect(screen.getByText(/택시 예상 대기와 해당 시각의 도로 주행시간을 분리/)).toBeVisible();
    const guide = screen.getByRole("region", { name: "경로 상세" });
    expect(within(guide).getByText("판교제2테크노밸리 승차에서 버스 9241번 승차")).toBeVisible();
    expect(within(guide).getByText("용인 방면")).toBeVisible();
    expect(within(guide).getByText("삼가역·두산위브 하차에서 하차")).toBeVisible();
    expect(within(guide).queryByText(/다음 ·/)).not.toBeInTheDocument();
    expect(screen.queryByText("제공사 추정 · 신뢰도 정보 없음")).not.toBeInTheDocument();
  });

  it.each(["MEDIUM", "LOW", "UNKNOWN"] as const)("hides vehicle values for %s mapping", async (grade) => {
    const user = userEvent.setup();
    render(<ResultPanel phase="COMPLETE" response={busResponse(grade)} problem={null} />);
    await user.click(screen.getByText("버스 탑승 정보"));

    expect(screen.getByText(/좌석·대기 정보를 정확히 확인하기 어려워/)).toBeInTheDocument();
    expect(screen.queryByText(/현재 확인된 좌석/)).not.toBeInTheDocument();
    expect(screen.queryByText(/좌석 부족 가능성/)).not.toBeInTheDocument();
    expect(screen.queryByText("vehicle-sensitive-ref")).not.toBeInTheDocument();
  });

  it("shows canonical Bus Intelligence values only for HIGH mapping", async () => {
    const user = userEvent.setup();
    render(<ResultPanel phase="COMPLETE" response={busResponse("HIGH")} problem={null} />);
    await user.click(screen.getByText("버스 탑승 정보"));

    expect(screen.getByText("현재 확인된 좌석 0석")).toBeInTheDocument();
    expect(screen.getByText(/좌석 부족 가능성/)).toBeInTheDocument();
    expect(screen.getByText(/약 3분 뒤 도착 · 늦으면 5분/)).toBeInTheDocument();
    expect(screen.queryByText(/P50|P90|ETA|매핑|대용값|Routing/)).not.toBeInTheDocument();
    expect(screen.queryByText("vehicle-sensitive-ref")).not.toBeInTheDocument();
  });

  it("fails closed when a live result violates the submitted strict taxi budget", () => {
    const response = busResponse("HIGH");
    const fastest = response.recommendations.fastest;
    if (fastest === null || fastest === undefined) throw new Error("Expected route");
    const invalid = { ...fastest, taxiCost: { ...fastest.taxiCost, expected: 12_000, upper: 15_000 } };
    render(<ResultPanel phase="COMPLETE" response={{ ...response, recommendations: { ...response.recommendations, fastest: invalid } }} problem={null} strictTaxiBudgetKrw={10_000} />);
    expect(screen.getByText("경로 정보를 검증할 수 없습니다")).toBeInTheDocument();
    expect(screen.queryByText("15,000원")).not.toBeInTheDocument();
  });
});
