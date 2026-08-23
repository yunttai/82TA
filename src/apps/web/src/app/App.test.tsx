import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

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
    if (url.includes("/api/v1/places/suggest")) {
      return new Response(JSON.stringify({
        items: [{
          displayName: "판교역",
          coordinate: { lon: 127.111159, lat: 37.394761 },
          provider: "KAKAO_LOCAL",
          providerPlaceId: "place-1",
          regionCode: "41135",
        }],
      }), { status: 200, headers: { "content-type": "application/json" } });
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
      distanceMeters: 8000,
      fare: { currency: "KRW", lower: 2800, expected: 2800, upper: 2800, origin: "PROVIDER_ESTIMATE" },
      geometry: { encoding: "NONE" },
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

describe("route search vertical slice", () => {
  it("renders an app-like mobile shell with labelled icon navigation and progressive map controls", () => {
    vi.stubGlobal("fetch", successfulFetch());
    render(<App />);

    expect(screen.getByRole("heading", { name: "어디로 갈까요?" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "모바일 주요 메뉴" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "길찾기" })).toHaveLength(2);
    const mapDetails = screen.getByText("지도에서 직접 위치 선택").closest("details");
    expect(mapDetails).not.toHaveAttribute("open");
  });

  it("renders canonical defaults without exposing raw coordinate inputs", () => {
    const fetchMock = successfulFetch();
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(screen.getByRole("combobox", { name: "출발지" })).toHaveValue("명지대학교 자연캠퍼스");
    expect(screen.getByRole("combobox", { name: "목적지" })).toHaveValue("판교역");
    expect(screen.getByRole("textbox", { name: /택시비 상한/ })).toHaveValue("10000");
    expect(screen.queryByRole("textbox", { name: "출발 경도" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "출발 위도" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "도착 경도" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "도착 위도" })).not.toBeInTheDocument();
  });

  it("posts only to the public route-search endpoint and preserves a partial null result", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    const fetchMock = successfulFetch();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findAllByText("일부 정보 제한")).toHaveLength(1);
    expect(screen.getByText("일부 정보 없이 계산한 결과입니다.")).toBeInTheDocument();
    expect(screen.getAllByText("추천 경로 없음")).toHaveLength(4);
    expect(screen.getByText("일부 교통 정보가 빠진 상태로 계산했습니다.")).toBeInTheDocument();

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
    expect(body).toContain('"maxAmount":10000');
    expect(body).toContain('"strict":true');
    expect(body).toContain('"requestedRecommendations":["FASTEST","STABLE","EFFICIENT","PUBLIC_TRANSIT_ONLY"]');
  });

  it("preserves quick budget, place swap, scheduled departure, deadline, and full constraint ranges", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    const fetchMock = successfulFetch();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole("button", { name: "출발지와 목적지 바꾸기" }));
    await user.click(screen.getByRole("button", { name: "5천원" }));
    await user.click(screen.getByRole("radio", { name: "지정 시각 출발" }));
    await user.clear(screen.getByLabelText("지정 출발 시각 · 한국 시간"));
    await user.type(screen.getByLabelText("지정 출발 시각 · 한국 시간"), "2030-01-02T10:30");
    await user.clear(screen.getByLabelText(/^도착 마감 시각/));
    await user.type(screen.getByLabelText(/^도착 마감 시각/), "2030-01-02T12:30");
    await user.selectOptions(screen.getByLabelText("최대 환승"), "8");
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findAllByText("일부 정보 제한")).toHaveLength(1);
    const routeCall = fetchMock.mock.calls.find(([input]) => (input instanceof Request ? input.url : input.toString()).endsWith("/api/v1/route-searches"));
    if (routeCall === undefined) throw new Error("Expected route request");
    const request = routeCall[0] instanceof Request ? routeCall[0].clone() : new Request(routeCall[0]);
    const body = await request.json() as PublicRouteSearchRequest;
    expect(body.origin.displayName).toBe("판교역");
    expect(body.destination.displayName).toBe("명지대학교 자연캠퍼스");
    expect(body.taxiBudget.maxAmount).toBe(5000);
    expect(body.departure.type).toBe("DEPART_AT");
    expect(body.departure.time).toBe("2030-01-02T01:30:00.000Z");
    expect(body.arrivalDeadline).toBe("2030-01-02T03:30:00.000Z");
    expect(body.preferences.maxTransfers).toBe(8);
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

  it("applies authenticated server preferences before the user edits the form", async () => {
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
    await waitFor(() => expect(screen.getByRole("textbox", { name: /택시비 상한/ })).toHaveValue("20000"));
    expect(screen.getByRole("textbox", { name: /최대 도보/ })).toHaveValue("30");
    expect(screen.getByRole("combobox", { name: "최대 환승" })).toHaveValue("6");
    expect(screen.getByRole("combobox", { name: "최대 택시 구간" })).toHaveValue("1");
    expect(screen.getByRole("combobox", { name: "추천 기준" })).toHaveValue("STABLE");
    expect(screen.getByRole("checkbox", { name: "계단이 있는 경로 피하기" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "휠체어 접근 가능한 경로 우선" })).toBeChecked();
  });

  it("retries an uncertain network result with the exact same body and idempotency key", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    const routeRequests: Request[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const session = sessionResponse(input);
      if (session !== null) return session;
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
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findByRole("heading", { name: "교통 정보를 불러올 수 없습니다" })).toBeInTheDocument();
  });

  it("uses a generic safe label for an unknown warning code", async () => {
    document.cookie = "csrftoken=csrf-test-token; Path=/; SameSite=Lax";
    vi.stubGlobal("fetch", successfulFetch(responseBody("COMPLETE", ["NEW_WARNING_CODE"])));
    const user = userEvent.setup();

    render(<App />);
    await user.click(screen.getByRole("button", { name: "내 예산으로 경로 찾기" }));

    expect(await screen.findByText("일부 정보를 확인할 수 없습니다.")).toBeInTheDocument();
    expect(screen.queryByText("NEW_WARNING_CODE")).not.toBeInTheDocument();
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
});

describe("Bus Intelligence mapping gate", () => {
  it.each(["MEDIUM", "LOW", "UNKNOWN"] as const)("hides vehicle values for %s mapping", async (grade) => {
    const user = userEvent.setup();
    render(<ResultPanel phase="COMPLETE" response={busResponse(grade)} problem={null} />);
    await user.click(screen.getByText("버스 좌석·대기 정보"));

    expect(screen.getByText(/노선·정류장 연결 신뢰도를 확인할 수 없어/)).toBeInTheDocument();
    expect(screen.queryByText(/관측 잔여 좌석/)).not.toBeInTheDocument();
    expect(screen.queryByText(/좌석 부족 확률/)).not.toBeInTheDocument();
    expect(screen.queryByText("vehicle-sensitive-ref")).not.toBeInTheDocument();
  });

  it("shows canonical Bus Intelligence values only for HIGH mapping", async () => {
    const user = userEvent.setup();
    render(<ResultPanel phase="COMPLETE" response={busResponse("HIGH")} problem={null} />);
    await user.click(screen.getByText("버스 좌석·대기 정보"));

    expect(screen.getByText("관측 잔여 좌석 0석")).toBeInTheDocument();
    expect(screen.getByText(/좌석 부족 확률/)).toBeInTheDocument();
    expect(screen.getAllByText("높음").length).toBeGreaterThan(0);
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
