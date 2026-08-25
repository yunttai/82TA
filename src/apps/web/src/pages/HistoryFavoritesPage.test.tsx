import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import canonicalResponse from "../../../../contracts/openapi/examples/public-route-search-response.json";
import { FavoritesPage, HistoryPage, SavedPlacesPage, StoredSearchPage } from "./ServicePages";
import type { PublicRouteSearchResponse } from "../shared/api/publicService";
import { clearSessionMemory, rememberUserSession } from "../shared/session/sessionMemory";

const documentVersion = "privacy-ko-2026.08.25";
const session = {
  subjectType: "USER",
  authenticated: true,
  expiresAt: "2099-08-25T00:00:00+09:00",
  email: "user@example.com",
  nickname: "사용자",
} as const;
const currentConsents = {
  items: [
    { consentType: "SEARCH_HISTORY", documentVersion, accepted: true, recordedAt: "2026-08-25T00:00:00+09:00" },
    { consentType: "PRECISE_LOCATION", documentVersion, accepted: true, recordedAt: "2026-08-25T00:00:00+09:00" },
  ],
};
const conditions = {
  schemaVersion: 1,
  departurePolicy: "DEPART_AT_CLICK",
  taxiBudget: { currency: "KRW", maxAmount: 7000, strict: true },
  preferences: {
    maxWalkSeconds: 7200,
    maxTransfers: 8,
    maxTaxiLegs: 3,
    allowTaxiBridge: true,
    avoidHighBusSeatRisk: false,
    allowedModes: ["WALK", "WAIT", "TRANSFER", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"],
    optimization: "BALANCED",
    accessibility: { avoidStairs: false, wheelchair: false },
  },
  requestedRecommendations: ["FASTEST", "STABLE", "EFFICIENT", "PUBLIC_TRANSIT_ONLY"],
};
const originPlace = {
  id: "11111111-1111-4111-8111-111111111111",
  label: "출발 별칭",
  place: { displayName: "세종대학교", coordinate: { lon: 127.073, lat: 37.55 }, provider: "KAKAO_LOCAL", providerPlaceId: "origin-place" },
  isSensitive: true,
  createdAt: "2026-08-25T00:00:00+09:00",
};
const destinationPlace = {
  id: "22222222-2222-4222-8222-222222222222",
  label: "도착 별칭",
  place: { displayName: "드론기업지원허브", coordinate: { lon: 127.1, lat: 37.4 }, provider: "KAKAO_LOCAL", providerPlaceId: "destination-place" },
  isSensitive: true,
  createdAt: "2026-08-25T00:00:00+09:00",
};
const favorite = {
  id: "33333333-3333-4333-8333-333333333333",
  nickname: "발표 가는 길",
  originSavedPlaceId: originPlace.id,
  destinationSavedPlaceId: destinationPlace.id,
  defaultConstraints: {},
  searchConditions: conditions,
  createdAt: "2026-08-25T00:00:00+09:00",
};
const favoriteCreationReceipt = {
  favoriteJourneyId: favorite.id,
  originSavedPlaceId: originPlace.id,
  destinationSavedPlaceId: destinationPlace.id,
  createdAt: favorite.createdAt,
  idempotencyExpiresAt: "2026-08-26T00:00:00+09:00",
};

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

function requestOf(input: RequestInfo | URL): Request {
  return input instanceof Request ? input : new Request(input);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function storedSearchResponse(searchId: string, originName: string, destinationName: string): PublicRouteSearchResponse {
  const response = structuredClone(canonicalResponse) as unknown as PublicRouteSearchResponse;
  for (const route of Object.values(response.recommendations)) {
    if (route == null || route.legs.length === 0) continue;
    route.legs[0]!.from.name = originName;
    route.legs[route.legs.length - 1]!.to.name = destinationName;
  }
  return { ...response, searchId, expiresAt: "2099-08-25T00:00:00+09:00" };
}

function accountFetch(options: {
  favorites?: unknown[];
  favoritesAfterCreate?: unknown[];
  favoriteListAfterCreateFailures?: number;
  consents?: typeof currentConsents;
  consentUnavailable?: boolean;
  capabilityUnavailable?: boolean;
  taxiBridgeSupported?: boolean;
  favoriteCreate?: (request: Request, attempt: number) => Response | Promise<Response>;
} = {}) {
  let favoriteCreateAttempt = 0;
  let favoriteCreated = false;
  let favoriteListAfterCreateFailures = options.favoriteListAfterCreateFailures ?? 0;
  return vi.fn(async (input: RequestInfo | URL) => {
    const request = requestOf(input);
    const url = new URL(request.url);
    if (url.pathname === "/api/v1/session") return json(session);
    if (url.pathname === "/api/v1/me/consents") return options.consentUnavailable === true
      ? json({ code: "UNAVAILABLE", message: "Unavailable" }, 503)
      : json(options.consents ?? currentConsents);
    if (url.pathname === "/api/v1/me/favorite-journeys") {
      if (favoriteCreated && favoriteListAfterCreateFailures > 0) {
        favoriteListAfterCreateFailures -= 1;
        return json({ code: "UNAVAILABLE", message: "Unavailable" }, 503);
      }
      return json(favoriteCreated ? options.favoritesAfterCreate ?? [favorite] : options.favorites ?? [favorite]);
    }
    if (url.pathname === "/api/v1/me/saved-places" && request.method === "GET") return json([originPlace, destinationPlace]);
    if (url.pathname.startsWith("/api/v1/me/saved-places/") && request.method === "PATCH") {
      const target = url.pathname.endsWith(originPlace.id) ? originPlace : destinationPlace;
      const body = await request.clone().json() as { label: string };
      return json({ ...target, label: body.label });
    }
    if (url.pathname === "/api/v1/me/preferences") return json({ defaultTaxiBudget: 7000, maxWalkSeconds: 7200, maxTransfers: 8, maxTaxiLegs: 3, optimizationProfile: "BALANCED", accessibility: { avoidStairs: false, wheelchair: false } });
    if (url.pathname === "/api/v1/support/capabilities") return options.capabilityUnavailable === true
      ? json({ code: "UNAVAILABLE", message: "Unavailable" }, 503)
      : json({ features: { taxiBridge: options.taxiBridgeSupported ?? true, busSeatRisk: false }, busIntelligenceCoverage: "UNAVAILABLE", degraded: [] });
    if (url.pathname === "/api/v1/places/suggest") {
      const isOrigin = url.searchParams.get("query")?.includes("세종") === true;
      return json({ items: [isOrigin ? originPlace.place : destinationPlace.place] });
    }
    if (url.pathname === "/api/v1/health") return json({ status: "ok" });
    if (url.pathname === "/api/v1/me/favorite-journeys/from-places" && request.method === "POST") {
      const attempt = favoriteCreateAttempt++;
      const response = options.favoriteCreate === undefined
        ? json(favoriteCreationReceipt, 201)
        : await options.favoriteCreate(request, attempt);
      if (response.status === 201) favoriteCreated = true;
      return response;
    }
    if (url.pathname === "/api/v1/route-searches" && request.method === "POST") return json({
      contractVersion: "1.5.0",
      searchId: "quick-search-1",
      status: "COMPLETE",
      generatedAt: "2026-08-25T00:00:00+09:00",
      expiresAt: "2099-08-25T00:00:00+09:00",
      recommendations: {},
      warnings: [],
      support: { features: {}, busIntelligenceCoverage: "UNAVAILABLE", degraded: [] },
    });
    return json({ code: "NOT_FOUND", message: "Not found" }, 404);
  });
}

async function fillFavoriteForm(user: ReturnType<typeof userEvent.setup>, nickname = "발표 가는 길") {
  await user.click(await screen.findByRole("button", { name: "자주 가는 경로 추가" }));
  await user.type(screen.getByLabelText("이름"), nickname);
  await user.type(screen.getByRole("combobox", { name: "출발지" }), "세종");
  await user.click(await screen.findByRole("option", { name: "세종대학교" }));
  await user.type(screen.getByRole("combobox", { name: "목적지" }), "드론");
  await user.click(await screen.findByRole("option", { name: "드론기업지원허브" }));
  await user.click(screen.getByRole("button", { name: "5천원" }));
}

function favoriteCreateRequests(fetchMock: ReturnType<typeof accountFetch>): Request[] {
  return fetchMock.mock.calls.flatMap(([input]) => {
    const request = requestOf(input);
    return new URL(request.url).pathname === "/api/v1/me/favorite-journeys/from-places" && request.method === "POST" ? [request] : [];
  });
}

beforeEach(() => {
  vi.stubEnv("VITE_PRIVACY_DOCUMENT_VERSION", documentVersion);
  document.cookie = "csrftoken=test-csrf; Path=/; SameSite=Lax";
  rememberUserSession(session);
});

afterEach(() => {
  document.cookie = "csrftoken=; Max-Age=0; Path=/";
  clearSessionMemory();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("HistoryPage", () => {
  it("shows the consent-off state for a stale history consent and does not load records", async () => {
    const fetchMock = accountFetch({ consents: { items: [{ ...currentConsents.items[0]!, documentVersion: "stale-version" }] } });
    vi.stubGlobal("fetch", fetchMock);
    render(<HistoryPage />);

    expect(await screen.findByText("검색 기록 저장이 꺼져 있어요")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "기록 저장 켜기" })).toHaveAttribute("href", "/privacy");
    expect(fetchMock.mock.calls.some(([input]) => new URL(requestOf(input).url).pathname === "/api/v1/route-searches")).toBe(false);
  });

  it("renders a coordinate-free, customer-language request summary without internal values", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(requestOf(input).url);
      if (url.pathname === "/api/v1/me/consents") return json(currentConsents);
      if (url.pathname === "/api/v1/route-searches") return json({ items: [{
        contractVersion: "1.5.0",
        searchId: "history-1",
        status: "PARTIAL",
        generatedAt: "2026-08-25T09:30:00+09:00",
        expiresAt: "2026-08-25T09:45:00+09:00",
        recommendations: {}, warnings: [],
        support: { features: {}, busIntelligenceCoverage: "UNAVAILABLE", degraded: [] },
        requestSummary: {
          originDisplayName: "세종대학교",
          destinationDisplayName: "드론기업지원허브",
          departureTime: "2026-08-25T09:30:00+09:00",
          arrivalDeadline: null,
          taxiBudget: { currency: "KRW", maxAmount: 7000, strict: true },
          preferences: conditions.preferences,
        },
      }] });
      return json({ code: "NOT_FOUND", message: "Not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<HistoryPage />);

    expect(await screen.findByRole("heading", { name: /세종대학교.*드론기업지원허브/ })).toBeInTheDocument();
    expect(screen.getByText("일부 정보 제한")).toBeInTheDocument();
    expect(screen.getByText("예상 요금 상한 10,000원")).toBeInTheDocument();
    const departureTime = screen.getByText("2026년 8월 25일 09:30");
    expect(departureTime).toHaveAttribute("datetime", "2026-08-25T09:30:00+09:00");
    expect(departureTime.parentElement).toHaveTextContent("출발 2026년 8월 25일 09:30");
    expect(screen.queryByText(/환승 최대/)).not.toBeInTheDocument();
    const historyCard = screen.getByRole("link", { name: "세종대학교에서 드론기업지원허브까지 저장 결과 확인" });
    expect(historyCard).toHaveAttribute("href", "/searches/history-1");
    expect(historyCard).toHaveClass("history-card-link");
    expect(document.body.textContent).not.toMatch(/PARTIAL|KAKAO|127\.073|history-1/);
  });

  it("clears a previous stored result and ignores responses from an older search id", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const third = deferred<Response>();
    const pending = new Map([
      ["first-search", first],
      ["second-search", second],
      ["third-search", third],
    ]);
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const searchId = new URL(requestOf(input).url).pathname.split("/").at(-1) ?? "";
      return pending.get(searchId)?.promise ?? Promise.resolve(json({ code: "NOT_FOUND", message: "Not found" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);

    const view = render(<StoredSearchPage searchId="first-search" />);
    await act(async () => { first.resolve(json(storedSearchResponse("first-search", "이전 출발지", "이전 목적지"))); });
    expect((await screen.findAllByText("이전 출발지")).length).toBeGreaterThan(0);

    view.rerender(<StoredSearchPage searchId="second-search" />);
    expect(screen.getByRole("heading", { name: "저장 결과를 불러오는 중…" })).toBeInTheDocument();
    expect(screen.queryByText("이전 출발지")).not.toBeInTheDocument();

    view.rerender(<StoredSearchPage searchId="third-search" />);
    await act(async () => { third.resolve(json(storedSearchResponse("third-search", "새 출발지", "새 목적지"))); });
    expect((await screen.findAllByText("새 출발지")).length).toBeGreaterThan(0);

    await act(async () => { second.resolve(json(storedSearchResponse("second-search", "늦게 온 출발지", "늦게 온 목적지"))); });
    await waitFor(() => {
      expect(screen.queryAllByText("새 출발지").length).toBeGreaterThan(0);
      expect(screen.queryByText("늦게 온 출발지")).not.toBeInTheDocument();
    });
  });
});

describe("SavedPlacesPage", () => {
  it("loads existing places but blocks exact-place creation when consent is stale, while allowing label-only rename", async () => {
    const fetchMock = accountFetch({
      consents: { items: [{ ...currentConsents.items[1]!, documentVersion: "stale-version" }] },
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "prompt").mockReturnValue("학교");
    const user = userEvent.setup();
    render(<SavedPlacesPage />);

    expect(await screen.findByText("정확한 위치 저장 동의가 필요해요")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "위치 저장 동의 확인" })).toHaveAttribute("href", "/privacy");
    expect(await screen.findByText("출발 별칭")).toBeInTheDocument();
    expect(screen.queryByText("저장 장소를 불러올 수 없습니다.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "민감 장소로 저장" })).toBeDisabled();

    await user.click(screen.getAllByRole("button", { name: "별칭 수정" })[0]!);
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => {
      const request = requestOf(input);
      return new URL(request.url).pathname === `/api/v1/me/saved-places/${originPlace.id}` && request.method === "PATCH";
    })).toBe(true));

    const mutations = fetchMock.mock.calls.map(([input]) => requestOf(input)).filter((request) => request.method === "POST");
    expect(mutations).toHaveLength(0);
    const consentIndex = fetchMock.mock.calls.findIndex(([input]) => new URL(requestOf(input).url).pathname === "/api/v1/me/consents");
    const placesIndex = fetchMock.mock.calls.findIndex(([input]) => {
      const request = requestOf(input);
      return new URL(request.url).pathname === "/api/v1/me/saved-places" && request.method === "GET";
    });
    expect(consentIndex).toBeGreaterThanOrEqual(0);
    expect(placesIndex).toBeGreaterThan(consentIndex);
  });

  it("shows the privacy action without a generic load failure when consent status cannot be checked", async () => {
    const fetchMock = accountFetch({ consentUnavailable: true });
    vi.stubGlobal("fetch", fetchMock);
    render(<SavedPlacesPage />);

    expect(await screen.findByText("정확한 위치 저장 동의가 필요해요")).toBeInTheDocument();
    expect(await screen.findByText("출발 별칭")).toBeInTheDocument();
    expect(screen.queryByText("저장 장소를 불러올 수 없습니다.")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => requestOf(input)).filter((request) => request.method === "POST")).toHaveLength(0);
  });
});

describe("FavoritesPage", () => {
  it("does not search on mount and sends one fresh public search on a quick-action double tap", async () => {
    const fetchMock = accountFetch();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<FavoritesPage />);

    const quickAction = await screen.findByRole("button", { name: /이 경로로 바로 길찾기/ });
    expect(quickAction).toHaveClass("favorite-route-action");
    expect(fetchMock.mock.calls.filter(([input]) => new URL(requestOf(input).url).pathname === "/api/v1/route-searches")).toHaveLength(0);
    await user.dblClick(within(quickAction).getByText("세종대학교"));

    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => {
      const request = requestOf(input);
      return new URL(request.url).pathname === "/api/v1/route-searches" && request.method === "POST";
    })).toHaveLength(1));
    const routeCall = fetchMock.mock.calls.find(([input]) => {
      const request = requestOf(input);
      return new URL(request.url).pathname === "/api/v1/route-searches" && request.method === "POST";
    });
    if (routeCall === undefined) throw new Error("Expected quick route search");
    const request = requestOf(routeCall[0]).clone();
    const body = await request.json();
    expect(body).toMatchObject({
      origin: originPlace.place,
      destination: destinationPlace.place,
      departure: { type: "DEPART_AT" },
      arrivalDeadline: null,
      taxiBudget: conditions.taxiBudget,
      saveToHistory: true,
    });
    expect(Date.now() - new Date(body.departure.time as string).getTime()).toBeLessThan(10_000);
    expect(JSON.stringify(body)).not.toContain(favorite.nickname);
    expect(JSON.stringify(body)).not.toContain(originPlace.label);
  });

  it("disables legacy favorites instead of guessing opaque conditions", async () => {
    const fetchMock = accountFetch({ favorites: [{ ...favorite, searchConditions: null }] });
    vi.stubGlobal("fetch", fetchMock);
    render(<FavoritesPage />);

    expect(await screen.findByText(/저장 조건이 없는 이전 즐겨찾기/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /이 경로로 바로 길찾기/ })).toBeDisabled();
  });

  it.each([
    ["지원하지 않을 때", { taxiBridgeSupported: false }],
    ["지원 여부 조회가 실패할 때", { capabilityUnavailable: true }],
  ])("fails closed for a taxi-bridge favorite when the capability is unavailable: %s", async (_label, options) => {
    const fetchMock = accountFetch(options);
    vi.stubGlobal("fetch", fetchMock);
    render(<FavoritesPage />);

    expect(await screen.findByText(/짧은 택시 이동 지원 여부를 확인할 수 없어/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /이 경로로 바로 길찾기/ })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([input]) => {
      const request = requestOf(input);
      return new URL(request.url).pathname === "/api/v1/route-searches" && request.method === "POST";
    })).toBe(false);
  });

  it("creates an arbitrary route atomically with typed canonical conditions", async () => {
    const fetchMock = accountFetch({ favorites: [] });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<FavoritesPage />);

    await fillFavoriteForm(user);
    await user.click(screen.getByRole("button", { name: "즐겨찾기에 저장" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => {
      const request = requestOf(input);
      return new URL(request.url).pathname === "/api/v1/me/favorite-journeys/from-places" && request.method === "POST";
    })).toBe(true));
    const createCall = fetchMock.mock.calls.find(([input]) => {
      const request = requestOf(input);
      return new URL(request.url).pathname === "/api/v1/me/favorite-journeys/from-places" && request.method === "POST";
    });
    if (createCall === undefined) throw new Error("Expected atomic favorite creation");
    const request = requestOf(createCall[0]).clone();
    const body = await request.json();
    expect(request.headers.get("Idempotency-Key")).toBeTruthy();
    expect(body).toMatchObject({
      nickname: "발표 가는 길",
      originPlace: { place: originPlace.place, isSensitive: true },
      destinationPlace: { place: destinationPlace.place, isSensitive: true },
      searchConditions: {
        schemaVersion: 1,
        departurePolicy: "DEPART_AT_CLICK",
        taxiBudget: { currency: "KRW", maxAmount: 2000, strict: true },
        requestedRecommendations: ["FASTEST", "STABLE", "EFFICIENT", "PUBLIC_TRANSIT_ONLY"],
      },
    });
    expect(body.searchConditions).not.toHaveProperty("saveToHistory");
    expect(body.searchConditions).not.toHaveProperty("departureTime");
    expect(body.searchConditions).not.toHaveProperty("arrivalDeadline");
    expect(screen.queryByRole("combobox", { name: "출발지" })).not.toBeInTheDocument();
    expect(screen.getByText(/즐겨찾기에 저장했어요.*한 번 누르면 바로 길찾기/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => new URL(requestOf(input).url).pathname === "/api/v1/me/favorite-journeys")).toHaveLength(2);
    expect(screen.getByText("발표 가는 길")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => {
      const request = requestOf(input);
      return new URL(request.url).pathname === "/api/v1/route-searches" && request.method === "POST";
    })).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: /이 경로로 바로 길찾기/ }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => {
      const request = requestOf(input);
      return new URL(request.url).pathname === "/api/v1/route-searches" && request.method === "POST";
    })).toHaveLength(1));
  });

  it("keeps the same create attempt until owner lists reload after a 201 receipt", async () => {
    const fetchMock = accountFetch({
      favorites: [],
      favoriteListAfterCreateFailures: 1,
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<FavoritesPage />);

    await fillFavoriteForm(user);
    await user.click(screen.getByRole("button", { name: "즐겨찾기에 저장" }));
    expect(await screen.findByText(/입력한 내용은 그대로 두었습니다/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "출발지" })).toHaveValue("세종대학교");

    await user.click(screen.getByRole("button", { name: "즐겨찾기에 저장" }));
    expect(await screen.findByText(/즐겨찾기에 저장했어요.*한 번 누르면 바로 길찾기/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "출발지" })).not.toBeInTheDocument();

    const requests = favoriteCreateRequests(fetchMock);
    expect(requests).toHaveLength(2);
    expect(requests[1]!.headers.get("Idempotency-Key")).toBe(requests[0]!.headers.get("Idempotency-Key"));
    expect(await requests[1]!.clone().text()).toBe(await requests[0]!.clone().text());
  });

  it("reuses the same idempotency key and exact body after a lost create response, then clears after success", async () => {
    const fetchMock = accountFetch({
      favorites: [],
      favoriteCreate: (_request, attempt) => {
        if (attempt === 0) throw new TypeError("response lost");
        return json({
          ...favoriteCreationReceipt,
          favoriteJourneyId: attempt === 2 ? "44444444-4444-4444-8444-444444444444" : favorite.id,
        }, 201);
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<FavoritesPage />);

    await fillFavoriteForm(user);
    await user.click(screen.getByRole("button", { name: "즐겨찾기에 저장" }));
    expect(await screen.findByText(/입력한 내용은 그대로 두었습니다/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "즐겨찾기에 저장" }));
    expect(await screen.findByText(/즐겨찾기에 저장했어요.*한 번 누르면 바로 길찾기/)).toBeInTheDocument();

    let requests = favoriteCreateRequests(fetchMock);
    expect(requests).toHaveLength(2);
    expect(requests[1]!.headers.get("Idempotency-Key")).toBe(requests[0]!.headers.get("Idempotency-Key"));
    expect(await requests[1]!.clone().text()).toBe(await requests[0]!.clone().text());

    await fillFavoriteForm(user);
    await user.click(screen.getByRole("button", { name: "즐겨찾기에 저장" }));
    await waitFor(() => expect(favoriteCreateRequests(fetchMock)).toHaveLength(3));
    requests = favoriteCreateRequests(fetchMock);
    expect(requests[2]!.headers.get("Idempotency-Key")).not.toBe(requests[0]!.headers.get("Idempotency-Key"));
    expect(await requests[2]!.clone().text()).toBe(await requests[0]!.clone().text());
  });

  it("uses a new idempotency key when the create body changes after failure", async () => {
    const fetchMock = accountFetch({
      favorites: [],
      favoriteCreate: (_request, attempt) => {
        if (attempt === 0) throw new TypeError("response lost");
        return json(favoriteCreationReceipt, 201);
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<FavoritesPage />);

    await fillFavoriteForm(user);
    await user.click(screen.getByRole("button", { name: "즐겨찾기에 저장" }));
    expect(await screen.findByText(/입력한 내용은 그대로 두었습니다/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("이름"));
    await user.type(screen.getByLabelText("이름"), "수정한 발표 길");
    await user.click(screen.getByRole("button", { name: "즐겨찾기에 저장" }));
    await waitFor(() => expect(favoriteCreateRequests(fetchMock)).toHaveLength(2));

    const requests = favoriteCreateRequests(fetchMock);
    expect(requests[1]!.headers.get("Idempotency-Key")).not.toBe(requests[0]!.headers.get("Idempotency-Key"));
    expect(await requests[1]!.clone().text()).not.toBe(await requests[0]!.clone().text());
  });
});
