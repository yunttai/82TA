import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { PlaceField } from "../features/place-search/PlaceField";
import { ResultPanel } from "../features/route-results/ResultPanel";
import {
  createFavoriteJourneyFromPlaces,
  createIdempotencyKey,
  createDataDeletion,
  createDataExport,
  createGuestSession,
  createSavedPlace,
  createRouteSearch,
  deleteFavoriteJourney,
  deleteSavedPlace,
  getDataDeletion,
  getDataExport,
  getPreferences,
  getPublicCapabilities,
  getRouteSearch,
  getCurrentSession,
  listFavoriteJourneys,
  listConsents,
  listRouteSearches,
  listSavedPlaces,
  loginWithEmail,
  registerWithEmail,
  revokeCurrentSession,
  recordConsent,
  updatePreferences,
  updateFavoriteJourney,
  updateSavedPlace,
  type FavoriteJourney,
  type FavoriteJourneyFromPlacesInput,
  type FavoriteJourneySearchConditionsV1,
  type ConsentRecord,
  type ConsentType,
  type DataRightsJob,
  type PlaceRef,
  type PublicCapabilities,
  type PublicRouteSearchResponse,
  type PublicRouteSearchRequest,
  type SavedPlace,
  type SessionContext,
  type UserPreferences,
} from "../shared/api/publicService";
import {
  expectedFareCapToTaxiBudgetKrw,
  maximumTaxiBudgetKrw,
  taxiBudgetToExpectedFareCapKrw,
} from "../features/route-search/fareBudget";
import {
  checkCurrentConsent,
  hasCurrentConsent,
} from "../shared/privacy/consentPolicy";
import {
  clearSessionMemory,
  currentGuestToken,
  inspectCurrentSession,
  rememberGuestSession,
  rememberUserSession,
} from "../shared/session/sessionMemory";

interface PageFrameProps {
  eyebrow: string;
  title: string;
  children: ReactNode;
}

function PageFrame({ eyebrow, title, children }: PageFrameProps) {
  return (
    <section className="page-panel" aria-labelledby="page-title">
      <p className="section-number">{eyebrow}</p>
      <h1 id="page-title" className="page-title">{title}</h1>
      {children}
    </section>
  );
}

function LoadMessage({ failed, empty }: { failed: boolean; empty: boolean }) {
  if (failed) return <p className="degraded-notice" role="status">계정 정보를 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.</p>;
  if (empty) return <p className="empty-copy">아직 표시할 항목이 없습니다.</p>;
  return <p className="empty-copy" role="status">불러오는 중…</p>;
}

function safeDownloadUrl(value: string | null | undefined): string | null {
  if (value == null) return null;
  try {
    const parsed = new URL(value, window.location.origin);
    return parsed.origin === window.location.origin || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function canonicalRequestFingerprint(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(canonicalRequestFingerprint).join(",")}]`;
  return `{${Object.entries(value)
    .filter(([, item]) => item !== undefined)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, item]) => `${JSON.stringify(key)}:${canonicalRequestFingerprint(item)}`)
    .join(",")}}`;
}

function formatDepartureTime(value: string): string {
  const departureTime = new Date(value);
  if (Number.isNaN(departureTime.getTime())) return "시각 확인 필요";
  return departureTime.toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
}

export function HistoryPage() {
  const [items, setItems] = useState<PublicRouteSearchResponse[] | null>(null);
  const [state, setState] = useState<"CHECKING" | "AUTH_REQUIRED" | "CONSENT_OFF" | "LOADING" | "READY" | "FAILED">("CHECKING");

  useEffect(() => {
    void inspectCurrentSession().then(async (session) => {
      if (session?.subjectType !== "USER") { setState("AUTH_REQUIRED"); return; }
      setState("LOADING");
      const consents = await listConsents();
      if (!consents.response.ok || consents.data === undefined) { setState("FAILED"); return; }
      if (!hasCurrentConsent(consents.data.items, "SEARCH_HISTORY")) { setState("CONSENT_OFF"); return; }
      const { data, response } = await listRouteSearches();
      if (!response.ok || data === undefined) { setState("FAILED"); return; }
      setItems(data.items);
      setState("READY");
    }).catch(() => setState("FAILED"));
  }, []);

  const statusLabel: Readonly<Record<PublicRouteSearchResponse["status"], string>> = {
    COMPLETE: "검색 완료",
    PARTIAL: "일부 정보 제한",
    NO_FEASIBLE_ROUTE: "조건에 맞는 경로 없음",
    PROVIDER_UNAVAILABLE: "교통 정보 확인 실패",
    FAILED: "검색 실패",
    EXPIRED: "이전 검색",
  };

  return (
    <PageFrame eyebrow="내 이동" title="검색 기록">
      <p className="page-lead">검색한 경로와 당시 조건을 다시 확인할 수 있어요.</p>
      {state === "AUTH_REQUIRED" && <div className="auth-required"><strong>로그인이 필요한 기능이에요</strong><p>로그인하면 검색한 경로를 기록에서 다시 확인할 수 있어요.</p><a className="primary-link" href="/account?next=/history">로그인하기</a></div>}
      {state === "CONSENT_OFF" && <div className="auth-required"><strong>검색 기록 저장이 꺼져 있어요</strong><p>동의하면 로그인 상태에서 검색할 때마다 기록이 저장됩니다.</p><a className="primary-link" href="/privacy">기록 저장 켜기</a></div>}
      {(state === "CHECKING" || state === "LOADING") && <p className="empty-copy" role="status">검색 기록을 불러오는 중입니다.</p>}
      {state === "FAILED" && <div className="degraded-notice" role="alert"><strong>검색 기록을 새로 불러오지 못했어요.</strong><p>잠시 후 다시 열어 주세요.</p></div>}
      {state === "READY" && items?.length === 0 && <div className="history-empty"><strong>아직 검색 기록이 없어요</strong><p>길찾기를 하면 여기에 자동으로 저장됩니다.</p><a className="primary-link" href="/search">길찾기 시작</a></div>}
      {state === "READY" && items !== null && items.length > 0 && (
        <ul className="resource-list history-list">
          {items.map((item) => (
            <li key={item.searchId}>
              <a
                className="history-card history-card-link"
                href={`/searches/${encodeURIComponent(item.searchId)}`}
                aria-label={item.requestSummary == null
                  ? `${statusLabel[item.status]} 저장 결과 확인`
                  : `${item.requestSummary.originDisplayName}에서 ${item.requestSummary.destinationDisplayName}까지 저장 결과 확인`}
              >
                <div className="history-card-heading"><strong>{statusLabel[item.status]}</strong><time dateTime={item.generatedAt}>{new Date(item.generatedAt).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" })}</time></div>
                {item.requestSummary == null ? <p className="legacy-guidance">이전 버전에서 저장한 기록이에요. 결과 화면에서 경로를 확인해 주세요.</p> : <>
                  <h2>{item.requestSummary.originDisplayName}<span aria-hidden="true">→</span>{item.requestSummary.destinationDisplayName}</h2>
                  <div className="condition-chips" aria-label="검색 조건">
                    <span>{item.requestSummary.taxiBudget.maxAmount === maximumTaxiBudgetKrw ? "예상 요금 상한 무관" : `예상 요금 상한 ${taxiBudgetToExpectedFareCapKrw(item.requestSummary.taxiBudget.maxAmount).toLocaleString("ko-KR")}원`}</span>
                    <span>{item.requestSummary.preferences.allowTaxiBridge === true ? "짧은 택시 이동 허용" : "대중교통 중심"}</span>
                    <span>출발 <time dateTime={item.requestSummary.departureTime}>{formatDepartureTime(item.requestSummary.departureTime)}</time></span>
                  </div>
                </>}
                <span className="card-primary-action" aria-hidden="true">저장 결과 확인</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </PageFrame>
  );
}

export function StoredSearchPage({ searchId, routeId, legId }: { searchId: string; routeId?: string; legId?: string }) {
  type LoadStatus = "LOADING" | "READY" | "NOT_FOUND" | "FORBIDDEN" | "FAILED";
  interface LoadState {
    searchId: string;
    status: LoadStatus;
    response: PublicRouteSearchResponse | null;
  }
  const [loadState, setLoadState] = useState<LoadState>(() => ({ searchId, status: "LOADING", response: null }));
  useEffect(() => {
    let active = true;
    setLoadState({ searchId, status: "LOADING", response: null });
    void getRouteSearch(searchId, currentGuestToken()).then(({ data, error, response: rawResponse }) => {
      if (!active) return;
      if (data !== undefined) { setLoadState({ searchId, status: "READY", response: data }); return; }
      if (rawResponse.status === 404) setLoadState({ searchId, status: "NOT_FOUND", response: null });
      else if (rawResponse.status === 403) setLoadState({ searchId, status: "FORBIDDEN", response: null });
      else {
        void error;
        setLoadState({ searchId, status: "FAILED", response: null });
      }
    }).catch(() => {
      if (active) setLoadState({ searchId, status: "FAILED", response: null });
    });
    return () => { active = false; };
  }, [searchId]);

  const currentLoadState: LoadState = loadState.searchId === searchId
    ? loadState
    : { searchId, status: "LOADING", response: null };
  const { response, status } = currentLoadState;

  if (response === null) {
    const message = status === "LOADING" ? "저장 결과를 불러오는 중…" : status === "NOT_FOUND" ? "검색 결과를 찾을 수 없습니다." : status === "FORBIDDEN" ? "이 검색 결과에 접근할 수 없습니다." : "검색 결과를 불러오지 못했습니다.";
    return <PageFrame eyebrow="저장 결과" title={message}><a href="/search">새 경로 검색</a></PageFrame>;
  }

  const routes = Object.values(response.recommendations).filter((route): route is NonNullable<typeof route> => route != null);
  const route = routeId === undefined ? undefined : routes.find((item) => item.routeId === routeId);
  if (routeId !== undefined && route === undefined) {
    return <PageFrame eyebrow="경로 상세" title="요청한 경로를 찾을 수 없습니다"><a href={`/searches/${encodeURIComponent(searchId)}`}>추천 목록으로 돌아가기</a></PageFrame>;
  }
  if (legId !== undefined && route?.legs.some((leg) => leg.legId === legId) !== true) {
    return <PageFrame eyebrow="버스 상세" title="요청한 이동 구간을 찾을 수 없습니다"><a href={`/searches/${encodeURIComponent(searchId)}/routes/${encodeURIComponent(routeId ?? "")}`}>경로 상세로 돌아가기</a></PageFrame>;
  }

  return (
    <div>
      {routeId !== undefined && <p className="context-banner">{legId === undefined ? "선택한 경로 상세" : "선택한 버스 구간 상세"}</p>}
      <ResultPanel phase={response.status} response={response} problem={null} {...(routeId === undefined ? {} : { initialRouteId: routeId })} {...(legId === undefined ? {} : { initialLegId: legId })} />
    </div>
  );
}

export function SavedPlacesPage() {
  const [items, setItems] = useState<SavedPlace[] | null>(null);
  const [place, setPlace] = useState<PlaceRef | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"IDLE" | "SAVING" | "FAILED">("IDLE");
  const [preciseLocationAllowed, setPreciseLocationAllowed] = useState<boolean | null>(null);

  async function reload() {
    const { data, response } = await listSavedPlaces();
    if (!response.ok || data === undefined) throw new Error("Saved places unavailable");
    setItems(data);
  }

  useEffect(() => {
    void (async () => {
      try {
        const consents = await listConsents();
        setPreciseLocationAllowed(consents.response.ok && consents.data !== undefined
          ? hasCurrentConsent(consents.data.items, "PRECISE_LOCATION")
          : false);
      } catch {
        setPreciseLocationAllowed(false);
      }
      try {
        await reload();
      } catch {
        setStatus("FAILED");
      }
    })();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (place === null) return;
    if (!await checkCurrentConsent("PRECISE_LOCATION")) { setPreciseLocationAllowed(false); return; }
    const data = new FormData(event.currentTarget);
    const rawLabel = data.get("label");
    if (typeof rawLabel !== "string" || rawLabel.trim().length === 0) return;
    setStatus("SAVING");
    try {
      const result = await createSavedPlace({ label: rawLabel.trim(), place, isSensitive: true });
      if (!result.response.ok) throw new Error("Save failed");
      setQuery("");
      setPlace(null);
      await reload();
      setStatus("IDLE");
    } catch {
      setStatus("FAILED");
    }
  }

  async function rename(item: SavedPlace) {
    const label = window.prompt("새 장소 별칭", item.label)?.trim();
    if (label === undefined || label.length === 0 || label === item.label) return;
    try {
      const result = await updateSavedPlace(item.id, { label });
      if (!result.response.ok) throw new Error("Update failed");
      await reload();
    } catch { setStatus("FAILED"); }
  }

  async function remove(item: SavedPlace) {
    if (!window.confirm(`‘${item.label}’ 저장 장소를 삭제할까요?`)) return;
    try {
      const result = await deleteSavedPlace(item.id);
      if (result.response.status !== 204) throw new Error("Delete failed");
      await reload();
    } catch { setStatus("FAILED"); }
  }

  return (
    <PageFrame eyebrow="내 장소" title="저장 장소">
      <p className="page-lead">정확한 위치는 민감정보로 취급하며 로그인한 82TA 계정에만 저장합니다.</p>
      <form className="resource-form" onSubmit={(event) => void submit(event)}>
        <label className="field"><span>별칭</span><input name="label" maxLength={50} placeholder="집, 학교, 회사" required /></label>
        <PlaceField label="장소 검색" value={query} onLabelChange={setQuery} onPlaceSelected={(selected) => { setPlace(selected); setQuery(selected.displayName); }} />
        {preciseLocationAllowed === false && <div className="privacy-cta"><strong>정확한 위치 저장 동의가 필요해요</strong><p>새 장소를 저장하려면 현재 개인정보 안내에 동의해 주세요. 기존 장소의 별칭은 계속 수정할 수 있어요.</p><a href="/privacy">위치 저장 동의 확인</a></div>}
        <button className="primary-button" type="submit" disabled={place === null || status === "SAVING" || preciseLocationAllowed !== true}>민감 장소로 저장</button>
        {status === "FAILED" && <p role="alert">저장 장소를 불러올 수 없습니다.</p>}
      </form>
      {items === null || items.length === 0 ? <LoadMessage failed={status === "FAILED"} empty={items?.length === 0} /> : (
        <ul className="resource-list">{items.map((item) => (
          <li key={item.id}>
            <div><strong>{item.label}</strong><span>{item.place.displayName}</span></div>
            <span>{item.isSensitive ? "민감 위치" : "일반 위치"}</span>
            <div className="item-actions"><button type="button" onClick={() => void rename(item)}>별칭 수정</button><button type="button" onClick={() => void remove(item)}>삭제</button></div>
          </li>
        ))}</ul>
      )}
    </PageFrame>
  );
}

export function FavoritesPage() {
  const [favorites, setFavorites] = useState<FavoriteJourney[] | null>(null);
  const [places, setPlaces] = useState<SavedPlace[]>([]);
  const [preferences, setPreferences] = useState<UserPreferences | null>(null);
  const [preciseLocationAllowed, setPreciseLocationAllowed] = useState(false);
  const [taxiBridgeSupported, setTaxiBridgeSupported] = useState<boolean | null>(null);
  const [pageState, setPageState] = useState<"LOADING" | "AUTH_REQUIRED" | "READY" | "FAILED">("LOADING");
  const [showForm, setShowForm] = useState(false);
  const [nickname, setNickname] = useState("");
  const [originQuery, setOriginQuery] = useState("");
  const [destinationQuery, setDestinationQuery] = useState("");
  const [origin, setOrigin] = useState<PlaceRef | null>(null);
  const [destination, setDestination] = useState<PlaceRef | null>(null);
  const [fareCap, setFareCap] = useState("10000");
  const [selectedFarePreset, setSelectedFarePreset] = useState<number | null>(10000);
  const [allowTaxiBridge, setAllowTaxiBridge] = useState(true);
  const [saveState, setSaveState] = useState<"IDLE" | "SAVING" | "DONE" | "FAILED" | "CONSENT_REQUIRED">("IDLE");
  const [activeFavoriteIds, setActiveFavoriteIds] = useState<ReadonlySet<string>>(() => new Set());
  const [favoriteError, setFavoriteError] = useState<Record<string, string>>({});
  const attempts = useRef(new Map<string, { idempotencyKey: string; request: PublicRouteSearchRequest }>());
  const activeSearches = useRef(new Set<string>());
  const favoriteCreateAttempt = useRef<{
    fingerprint: string;
    idempotencyKey: string;
    body: FavoriteJourneyFromPlacesInput;
  } | null>(null);

  async function reload() {
    const [favoriteResult, placeResult, preferenceResult, consentResult, capabilityResult] = await Promise.all([
      listFavoriteJourneys(),
      listSavedPlaces(),
      getPreferences(),
      listConsents(),
      getPublicCapabilities(),
    ]);
    if (!favoriteResult.response.ok || favoriteResult.data === undefined || !placeResult.response.ok || placeResult.data === undefined
      || !preferenceResult.response.ok || preferenceResult.data === undefined || !consentResult.response.ok || consentResult.data === undefined) {
      throw new Error("Favorites unavailable");
    }
    setFavorites(favoriteResult.data);
    setPlaces(placeResult.data);
    setPreferences(preferenceResult.data);
    setPreciseLocationAllowed(hasCurrentConsent(consentResult.data.items, "PRECISE_LOCATION"));
    setTaxiBridgeSupported(capabilityResult.response.ok && capabilityResult.data !== undefined
      ? capabilityResult.data.features?.taxiBridge === true
      : null);
  }

  useEffect(() => {
    void inspectCurrentSession().then((session) => {
      if (session?.subjectType !== "USER") { setPageState("AUTH_REQUIRED"); return; }
      void reload().then(() => setPageState("READY")).catch(() => setPageState("FAILED"));
    }).catch(() => setPageState("FAILED"));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (origin === null || destination === null || preferences === null || nickname.trim().length === 0) return;
    const expectedFareCap = Number(fareCap);
    if (!Number.isInteger(expectedFareCap) || expectedFareCap < 0 || expectedFareCap > maximumTaxiBudgetKrw) { setSaveState("FAILED"); return; }
    if (!await checkCurrentConsent("PRECISE_LOCATION")) { setPreciseLocationAllowed(false); setSaveState("CONSENT_REQUIRED"); return; }
    const searchConditions: FavoriteJourneySearchConditionsV1 = {
      schemaVersion: 1,
      departurePolicy: "DEPART_AT_CLICK",
      taxiBudget: {
        currency: "KRW",
        maxAmount: expectedFareCapToTaxiBudgetKrw(expectedFareCap, selectedFarePreset === maximumTaxiBudgetKrw),
        strict: true,
      },
      preferences: {
        maxWalkSeconds: preferences.maxWalkSeconds,
        maxTransfers: preferences.maxTransfers,
        maxTaxiLegs: preferences.maxTaxiLegs,
        allowTaxiBridge: taxiBridgeSupported === true && allowTaxiBridge,
        avoidHighBusSeatRisk: false,
        allowedModes: ["WALK", "WAIT", "TRANSFER", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"],
        optimization: preferences.optimizationProfile,
        ...(preferences.accessibility === undefined ? {} : { accessibility: preferences.accessibility }),
      },
      requestedRecommendations: ["FASTEST", "STABLE", "EFFICIENT", "PUBLIC_TRANSIT_ONLY"],
    };
    const body: FavoriteJourneyFromPlacesInput = {
      nickname: nickname.trim(),
      originPlace: { label: origin.displayName.slice(0, 50), place: origin, isSensitive: true },
      destinationPlace: { label: destination.displayName.slice(0, 50), place: destination, isSensitive: true },
      searchConditions,
    };
    const fingerprint = canonicalRequestFingerprint(body);
    if (favoriteCreateAttempt.current?.fingerprint !== fingerprint) {
      favoriteCreateAttempt.current = { fingerprint, idempotencyKey: createIdempotencyKey(), body };
    }
    const attempt = favoriteCreateAttempt.current;
    setSaveState("SAVING");
    try {
      const result = await createFavoriteJourneyFromPlaces(attempt.body, attempt.idempotencyKey);
      if (result.response.status !== 201 || result.data === undefined) throw new Error("Favorite save failed");
      await reload();
      favoriteCreateAttempt.current = null;
      setNickname(""); setOriginQuery(""); setDestinationQuery(""); setOrigin(null); setDestination(null);
      setShowForm(false);
      setSaveState("DONE");
    } catch {
      setSaveState("FAILED");
    }
  }

  async function rename(item: FavoriteJourney) {
    const nickname = window.prompt("새 여정 이름", item.nickname)?.trim();
    if (nickname === undefined || nickname.length === 0 || nickname === item.nickname) return;
    try {
      const result = await updateFavoriteJourney(item.id, { nickname });
      if (!result.response.ok) throw new Error("Favorite update failed");
      await reload();
    } catch { setPageState("FAILED"); }
  }

  async function remove(item: FavoriteJourney) {
    if (!window.confirm(`‘${item.nickname}’ 즐겨찾기를 삭제할까요?`)) return;
    try {
      const result = await deleteFavoriteJourney(item.id);
      if (result.response.status !== 204) throw new Error("Favorite delete failed");
      await reload();
    } catch { setFavoriteError((current) => ({ ...current, [item.id]: "즐겨찾기를 삭제하지 못했어요. 잠시 후 다시 시도해 주세요." })); }
  }

  function routeRequest(item: FavoriteJourney, originPlace: SavedPlace, destinationPlace: SavedPlace): PublicRouteSearchRequest | null {
    if (item.searchConditions == null) return null;
    return {
      origin: originPlace.place,
      destination: destinationPlace.place,
      departure: { type: "DEPART_AT", time: new Date().toISOString() },
      arrivalDeadline: null,
      taxiBudget: item.searchConditions.taxiBudget,
      preferences: item.searchConditions.preferences,
      requestedRecommendations: item.searchConditions.requestedRecommendations,
      saveToHistory: false,
    };
  }

  async function quickSearch(item: FavoriteJourney, originPlace: SavedPlace, destinationPlace: SavedPlace) {
    if (activeSearches.current.has(item.id) || !navigator.onLine) return;
    activeSearches.current.add(item.id);
    setActiveFavoriteIds((current) => new Set([...current, item.id]));
    setFavoriteError((current) => ({ ...current, [item.id]: "" }));
    let navigationStarted = false;
    try {
      let attempt = attempts.current.get(item.id);
      if (attempt === undefined) {
        const request = routeRequest(item, originPlace, destinationPlace);
        if (request === null) throw new Error("LEGACY");
        request.saveToHistory = await checkCurrentConsent("SEARCH_HISTORY");
        attempt = { idempotencyKey: createIdempotencyKey(), request };
        attempts.current.set(item.id, attempt);
      }
      const result = await createRouteSearch(attempt.request, attempt.idempotencyKey);
      if (!result.response.ok || result.data === undefined) throw new Error("SEARCH_FAILED");
      attempts.current.delete(item.id);
      const destinationPath = `/searches/${encodeURIComponent(result.data.searchId)}`;
      navigationStarted = true;
      window.history.pushState(null, "", destinationPath);
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (error) {
      setFavoriteError((current) => ({ ...current, [item.id]: error instanceof Error && error.message === "LEGACY"
        ? "저장 조건이 없는 이전 즐겨찾기예요. 새로 저장해 주세요."
        : "경로를 찾지 못했어요. 저장한 조건은 그대로 유지됩니다." }));
    } finally {
      if (!navigationStarted) {
        activeSearches.current.delete(item.id);
        setActiveFavoriteIds((current) => {
          const next = new Set(current);
          next.delete(item.id);
          return next;
        });
      }
    }
  }

  return (
    <PageFrame eyebrow="내 이동" title="즐겨찾기">
      <p className="page-lead">자주 가는 경로와 조건을 저장하고, 버튼 한 번으로 바로 길찾기해요.</p>
      {pageState === "AUTH_REQUIRED" && <div className="auth-required"><strong>로그인이 필요한 기능이에요</strong><p>로그인하면 자주 가는 경로를 안전하게 저장할 수 있어요.</p><a className="primary-link" href="/account?next=/favorites">로그인하기</a></div>}
      {pageState === "LOADING" && <p className="empty-copy" role="status">즐겨찾기를 불러오는 중입니다.</p>}
      {pageState === "FAILED" && <p className="degraded-notice" role="alert">즐겨찾기를 불러오지 못했어요. 잠시 후 다시 열어 주세요.</p>}
      {pageState === "READY" && <>
        <button className="primary-button favorite-add-button" type="button" onClick={() => setShowForm((current) => !current)} aria-expanded={showForm} aria-controls="favorite-create-form">{showForm ? "추가 닫기" : "자주 가는 경로 추가"}</button>
        {showForm && <form id="favorite-create-form" className="resource-form favorite-create-form" onSubmit={(event) => void submit(event)}>
          <label className="field"><span>이름</span><input value={nickname} onChange={(event) => setNickname(event.currentTarget.value)} maxLength={100} placeholder="출근길, 학교 가는 길" required /></label>
          <PlaceField label="출발지" value={originQuery} onLabelChange={(value) => { setOriginQuery(value); setOrigin(null); }} onPlaceSelected={(place) => { setOrigin(place); setOriginQuery(place.displayName); }} />
          <PlaceField label="목적지" value={destinationQuery} onLabelChange={(value) => { setDestinationQuery(value); setDestination(null); }} onPlaceSelected={(place) => { setDestination(place); setDestinationQuery(place.displayName); }} />
          <div className="budget-section">
            <span className="budget-title">예상 요금 상한</span>
            <div className="budget-presets" role="group" aria-label="즐겨찾기 예상 요금 상한 빠른 선택">{([[maximumTaxiBudgetKrw, "무관"], [5000, "5천원"], [10000, "1만원"], [20000, "2만원"]] as const).map(([amount, label]) => <button key={amount} type="button" aria-pressed={selectedFarePreset === amount} onClick={() => { setSelectedFarePreset(amount); setFareCap(String(amount)); }}>{label}</button>)}</div>
            <label className="field budget-field"><span>요금 상한 직접 입력</span><span className="input-suffix"><input inputMode="numeric" min={0} max={maximumTaxiBudgetKrw} value={selectedFarePreset === maximumTaxiBudgetKrw ? "" : fareCap} placeholder={selectedFarePreset === maximumTaxiBudgetKrw ? "무관 선택됨" : undefined} onFocus={() => { if (selectedFarePreset === maximumTaxiBudgetKrw) setFareCap(""); setSelectedFarePreset(null); }} onChange={(event) => { setSelectedFarePreset(null); setFareCap(event.currentTarget.value); }} required={selectedFarePreset !== maximumTaxiBudgetKrw} /><span>원</span></span></label>
          </div>
          <label className="check-field"><input type="checkbox" checked={taxiBridgeSupported === true && allowTaxiBridge} disabled={taxiBridgeSupported !== true} onChange={(event) => setAllowTaxiBridge(event.currentTarget.checked)} /><span>대중교통 사이 짧은 택시 이동 허용</span></label>
          {!preciseLocationAllowed && <div className="privacy-cta"><strong>정확한 위치 저장 동의가 필요해요</strong><p>즐겨찾기는 선택한 출발지와 목적지를 계정에 저장합니다.</p><a href="/privacy">위치 저장 동의 확인</a></div>}
          <button className="primary-button" type="submit" disabled={saveState === "SAVING" || origin === null || destination === null || preferences === null || !preciseLocationAllowed}>{saveState === "SAVING" ? "저장하는 중…" : "즐겨찾기에 저장"}</button>
        </form>}
        <div className="form-announcement" aria-live="polite">{saveState === "DONE" ? "즐겨찾기에 저장했어요. 아래 버튼을 한 번 누르면 바로 길찾기합니다." : saveState === "FAILED" ? "즐겨찾기를 저장하지 못했어요. 입력한 내용은 그대로 두었습니다." : saveState === "CONSENT_REQUIRED" ? "위치 저장 동의를 다시 확인해 주세요." : ""}</div>
        {favorites?.length === 0 && <div className="history-empty"><strong>아직 즐겨찾는 경로가 없어요</strong><p>자주 가는 출발지와 목적지, 예상 요금 상한을 저장해 보세요.</p></div>}
        {favorites !== null && favorites.length > 0 && <ul className="resource-list favorite-list">{favorites.map((item) => {
          const originPlace = places.find((place) => place.id === item.originSavedPlaceId);
          const destinationPlace = places.find((place) => place.id === item.destinationSavedPlaceId);
          const conditions = item.searchConditions;
          const unsupported = conditions?.preferences.allowTaxiBridge === true && taxiBridgeSupported !== true;
          const runnable = originPlace !== undefined && destinationPlace !== undefined && conditions != null && !unsupported;
          return <li key={item.id}><article className="favorite-card">
            <button className="favorite-route-action" type="button" disabled={!runnable || activeFavoriteIds.has(item.id) || !navigator.onLine} onClick={() => { if (originPlace !== undefined && destinationPlace !== undefined) void quickSearch(item, originPlace, destinationPlace); }}>
              <span className="favorite-card-name">{item.nickname}</span>
              <span className="favorite-route-title"><span>{originPlace?.place.displayName ?? "저장 장소 확인 필요"}</span><span aria-hidden="true">→</span><span>{destinationPlace?.place.displayName ?? "저장 장소 확인 필요"}</span></span>
              {conditions == null ? <span className="legacy-guidance">저장 조건이 없는 이전 즐겨찾기예요. 새 조건으로 다시 저장해 주세요.</span> : <span className="condition-chips"><span>{conditions.taxiBudget.maxAmount === maximumTaxiBudgetKrw ? "예상 요금 상한 무관" : `예상 요금 상한 ${taxiBudgetToExpectedFareCapKrw(conditions.taxiBudget.maxAmount).toLocaleString("ko-KR")}원`}</span><span>{conditions.preferences.allowTaxiBridge === true ? "짧은 택시 이동 허용" : "대중교통 중심"}</span></span>}
              {unsupported && <span className="legacy-guidance">현재는 짧은 택시 이동 지원 여부를 확인할 수 없어 이 조건으로 검색할 수 없어요.</span>}
              <span className="card-primary-action">{activeFavoriteIds.has(item.id) ? `‘${item.nickname}’ 경로를 찾는 중…` : navigator.onLine ? "이 경로로 바로 길찾기" : "인터넷 연결 후 길찾기"}</span>
            </button>
            <div className="item-actions"><button type="button" onClick={() => void rename(item)}>이름 수정</button><button type="button" onClick={() => void remove(item)}>삭제</button></div>
            {favoriteError[item.id] && <p className="favorite-error" role="alert">{favoriteError[item.id]}</p>}
          </article></li>;
        })}</ul>}
      </>}
    </PageFrame>
  );
}

export function PreferencesPage() {
  const [preferences, setPreferences] = useState<UserPreferences | null>(null);
  const [etag, setEtag] = useState<string | undefined>();
  const [status, setStatus] = useState<"LOADING" | "READY" | "SAVING" | "DONE" | "CONFLICT" | "FAILED">("LOADING");

  async function reloadPreferences() {
    const { data, response } = await getPreferences();
    if (!response.ok || data === undefined) throw new Error("Preferences unavailable");
    setPreferences(data);
    setEtag(response.headers.get("etag") ?? undefined);
    setStatus("READY");
  }

  useEffect(() => { void reloadPreferences().catch(() => setStatus("FAILED")); }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (preferences === null) return;
    setStatus("SAVING");
    try {
      const { data, response } = await updatePreferences(preferences, etag);
      if (response.status === 409) { setStatus("CONFLICT"); return; }
      if (!response.ok || data === undefined) throw new Error("Preferences update failed");
      setPreferences(data);
      setEtag(response.headers.get("etag") ?? undefined);
      setStatus("DONE");
    } catch {
      setStatus("FAILED");
    }
  }

  return (
    <PageFrame eyebrow="맞춤 설정" title="이동 선호">
      <p className="page-lead">이 값은 새 검색의 기본값이며 서버가 반환한 경로의 시간·비용·순위를 다시 계산하지 않습니다.</p>
      {preferences === null ? <LoadMessage failed={status === "FAILED"} empty={false} /> : (
        <form className="resource-form" onSubmit={(event) => void submit(event)}>
          <div className="form-grid">
            <label className="field"><span>기본 택시 예산(원)</span><input type="number" min={0} max={500000} step={1} value={preferences.defaultTaxiBudget} onChange={(event) => setPreferences({ ...preferences, defaultTaxiBudget: Number(event.currentTarget.value) })} /></label>
            <label className="field"><span>최대 도보(초)</span><input type="number" min={0} max={7200} value={preferences.maxWalkSeconds} onChange={(event) => setPreferences({ ...preferences, maxWalkSeconds: Number(event.currentTarget.value) })} /></label>
            <label className="field"><span>최대 환승</span><input type="number" min={0} max={8} value={preferences.maxTransfers} onChange={(event) => setPreferences({ ...preferences, maxTransfers: Number(event.currentTarget.value) })} /></label>
            <label className="field"><span>최대 택시 구간</span><input type="number" min={0} max={3} value={preferences.maxTaxiLegs} onChange={(event) => setPreferences({ ...preferences, maxTaxiLegs: Number(event.currentTarget.value) })} /></label>
            <label className="field"><span>추천 기준</span><select value={preferences.optimizationProfile} onChange={(event) => {
              const value = event.currentTarget.value;
              if (value === "FASTEST" || value === "STABLE" || value === "EFFICIENT" || value === "BALANCED") setPreferences({ ...preferences, optimizationProfile: value });
            }}><option value="BALANCED">균형</option><option value="FASTEST">빠른 도착</option><option value="STABLE">안정적인 도착</option><option value="EFFICIENT">비용 효율</option></select></label>
          </div>
          <fieldset className="preference-accessibility">
            <legend>접근성 선호</legend>
            <label className="check-field"><input type="checkbox" checked={preferences.accessibility?.avoidStairs === true} onChange={(event) => setPreferences({ ...preferences, accessibility: { avoidStairs: event.currentTarget.checked, wheelchair: preferences.accessibility?.wheelchair ?? false } })} /><span>계단이 있는 경로 피하기</span></label>
            <label className="check-field"><input type="checkbox" checked={preferences.accessibility?.wheelchair === true} onChange={(event) => setPreferences({ ...preferences, accessibility: { avoidStairs: preferences.accessibility?.avoidStairs ?? false, wheelchair: event.currentTarget.checked } })} /><span>휠체어 접근 가능한 경로 우선</span></label>
            <p>교통 제공 범위에 따라 실제 접근성을 보장하지 않습니다. 검색 결과의 지원 정보와 경고를 확인해 주세요.</p>
          </fieldset>
          <button className="primary-button" type="submit" disabled={status === "SAVING"}>{status === "SAVING" ? "저장 중…" : "선호 저장"}</button>
          {preferences.updatedAt !== undefined && <p className="resource-meta">최근 저장 {new Date(preferences.updatedAt).toLocaleString("ko-KR")}</p>}
          {status === "DONE" && <p role="status">선호를 저장했습니다.</p>}
          {status === "CONFLICT" && <div className="degraded-notice" role="alert"><p>다른 기기에서 선호가 변경되었습니다. 자동으로 덮어쓰지 않습니다.</p><button className="secondary-button" type="button" onClick={() => void reloadPreferences().catch(() => setStatus("FAILED"))}>서버 최신값 불러오기</button></div>}
          {status === "FAILED" && <p role="alert">이동 선호를 저장할 수 없습니다.</p>}
        </form>
      )}
    </PageFrame>
  );
}

const featureLabels: Readonly<Record<string, string>> = {
  currentTransit: "현재 대중교통", futureTransit: "미래 대중교통", currentTaxi: "현재 택시",
  futureTaxi: "미래 택시", multiDestinationTaxi: "택시 다중 목적지", busSeatRisk: "버스 좌석 정보",
  busEtaModel: "버스 도착 예측", taxiBridge: "택시 연결", realtimeRerouting: "실시간 재추천",
};

const busInformationLabels = {
  LIVE: "실시간 정보 제공",
  PARTIAL: "일부 정보 제공",
  HISTORICAL: "과거 운행 정보 제공",
  UNSUPPORTED: "좌석 정보 미지원",
  UNKNOWN: "확인 중",
} as const;

export function SupportPage() {
  const [support, setSupport] = useState<PublicCapabilities | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    void getPublicCapabilities().then(({ data, response }) => {
      if (!response.ok || data === undefined) setFailed(true); else setSupport(data);
    }).catch(() => setFailed(true));
  }, []);
  return (
    <PageFrame eyebrow="서비스 상태" title="지원 범위">
      <p className="page-lead">현재 이용할 수 있는 지역과 교통 정보를 확인하세요.</p>
      {support === null ? <LoadMessage failed={failed} empty={false} /> : (
        <>
          <p className="coverage-chip">버스 좌석 정보: {busInformationLabels[support.busIntelligenceCoverage ?? "UNKNOWN"]}</p>
          <ul className="capability-grid" aria-label="지역 지원">
            <li><span>출발 지역</span><strong>{support.region?.originSupported === true ? "지원" : support.region?.originSupported === false ? "미지원" : "확인 불가"}</strong></li>
            <li><span>도착 지역</span><strong>{support.region?.destinationSupported === true ? "지원" : support.region?.destinationSupported === false ? "미지원" : "확인 불가"}</strong></li>
          </ul>
          <ul className="capability-grid">{Object.entries(support.features).map(([name, enabled]) => (
            <li key={name}><span>{featureLabels[name] ?? "새 지원 항목"}</span><strong>{enabled === true ? "지원" : enabled === false ? "미지원" : "확인 중"}</strong></li>
          ))}</ul>
          {support.degraded.length > 0 && <div className="degraded-notice"><strong>현재 제한</strong><p>일부 기능이 제한되어 있습니다. 검색 결과의 안내를 확인해 주세요.</p></div>}
        </>
      )}
    </PageFrame>
  );
}

export function AccountPage() {
  const [session, setSession] = useState<SessionContext | null>(null);
  const [guestToken, setGuestToken] = useState<string | undefined>(currentGuestToken());
  const [status, setStatus] = useState<"LOADING" | "READY" | "SIGNED_OUT" | "FAILED">("LOADING");
  const [mode, setMode] = useState<"LOGIN" | "REGISTER">("LOGIN");
  const [authStatus, setAuthStatus] = useState<"IDLE" | "SENDING" | "INVALID" | "INVALID_INPUT" | "PRIVACY_REQUIRED" | "UPDATE_REQUIRED" | "SECURITY_EXPIRED" | "RATE_LIMITED" | "OFFLINE" | "DUPLICATE" | "FAILED">("IDLE");

  useEffect(() => {
    void inspectCurrentSession().then((current) => {
      if (current === null) setStatus("SIGNED_OUT");
      else { setSession(current); setStatus("READY"); }
    }).catch(() => setStatus("FAILED"));
  }, []);

  async function startGuestSession() {
    try {
      const created = await createGuestSession();
      if (!created.response.ok || created.data === undefined) throw new Error("Guest session unavailable");
      setGuestToken(created.data.guestToken);
      const current = await getCurrentSession(created.data.guestToken);
      if (!current.response.ok || current.data === undefined) throw new Error("Guest session invalid");
      rememberGuestSession(created.data.guestToken, current.data);
      setSession(current.data);
      setStatus("READY");
    } catch { setStatus("FAILED"); }
  }

  async function signOut() {
    try {
      const result = await revokeCurrentSession(guestToken);
      if (!result.response.ok) throw new Error("Session revoke failed");
      clearSessionMemory();
      setGuestToken(undefined);
      setSession(null);
      setStatus("SIGNED_OUT");
    } catch { setStatus("FAILED"); }
  }

  async function submitCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = form.get("email");
    const password = form.get("password");
    if (typeof email !== "string" || typeof password !== "string") return;
    const privacyAccepted = form.get("requiredPrivacyAccepted") === "on";
    if (mode === "REGISTER" && !privacyAccepted) { setAuthStatus("PRIVACY_REQUIRED"); return; }
    setAuthStatus("SENDING");
    try {
      const documentVersion = import.meta.env.VITE_PRIVACY_DOCUMENT_VERSION;
      if (mode === "REGISTER" && (documentVersion === undefined || documentVersion.length === 0)) {
        setAuthStatus("UPDATE_REQUIRED");
        return;
      }
      const result = mode === "LOGIN"
        ? await loginWithEmail({ email: email.trim(), password })
        : await registerWithEmail({
            email: email.trim(),
            password,
            nickname: String(form.get("nickname") ?? "").trim(),
            documentVersion: documentVersion ?? "",
            requiredPrivacyAccepted: true,
            optionalConsents: {
              SEARCH_HISTORY: form.get("SEARCH_HISTORY") === "on",
              PRECISE_LOCATION: form.get("PRECISE_LOCATION") === "on",
              PRODUCT_ANALYTICS: form.get("PRODUCT_ANALYTICS") === "on",
              ROUTING_FEEDBACK: form.get("ROUTING_FEEDBACK") === "on",
            },
          });
      if (result.response.status === 401) { setAuthStatus("INVALID"); return; }
      if (result.response.status === 409) { setAuthStatus("DUPLICATE"); return; }
      if (result.response.status === 400) {
        const policyChanged = result.error?.violations.some((violation) => violation.field === "documentVersion") === true;
        setAuthStatus(policyChanged ? "UPDATE_REQUIRED" : "INVALID_INPUT");
        if (policyChanged && "serviceWorker" in navigator) {
          void navigator.serviceWorker.getRegistration().then((registration) => registration?.update()).catch(() => undefined);
        }
        return;
      }
      if (result.response.status === 403) { setAuthStatus("SECURITY_EXPIRED"); return; }
      if (result.response.status === 429) { setAuthStatus("RATE_LIMITED"); return; }
      if (!result.response.ok || result.data === undefined) throw new Error("Authentication failed");
      rememberUserSession(result.data);
      setGuestToken(undefined);
      setSession(result.data);
      setStatus("READY");
      setAuthStatus("IDLE");
      const next = new URLSearchParams(window.location.search).get("next");
      if (next === "/history" || next === "/favorites") window.location.assign(next);
    } catch {
      setAuthStatus(navigator.onLine ? "FAILED" : "OFFLINE");
    }
  }

  return (
    <PageFrame eyebrow="계정" title={session?.subjectType === "USER" ? "로그인 상태" : "로그인하고 저장하기"}>
      <p className="page-lead">길찾기는 로그인 없이 사용할 수 있어요. 로그인하면 검색 기록과 즐겨찾기, 설정을 계정에 안전하게 저장할 수 있습니다.</p>
      {session?.subjectType === "USER" && <section className="account-profile-card" aria-label="로그인 상태"><div className="profile-avatar" aria-hidden="true">{(session.nickname ?? session.email ?? "8").slice(0, 1).toUpperCase()}</div><div><span className="profile-status">로그인됨</span><strong>{session.nickname ?? "82TA 사용자"}</strong><small>{session.email}</small><small>{new Date(session.expiresAt).toLocaleString("ko-KR")}까지 유지</small></div></section>}
      {session?.subjectType === "GUEST" && <div className="coverage-chip">게스트 · {new Date(session.expiresAt).toLocaleString("ko-KR")}까지</div>}
      {session?.subjectType !== "USER" && (
        <div className="auth-card">
          <div className="auth-mode" role="tablist" aria-label="계정 방식">
            <button type="button" role="tab" aria-selected={mode === "LOGIN"} onClick={() => { setMode("LOGIN"); setAuthStatus("IDLE"); }}>로그인</button>
            <button type="button" role="tab" aria-selected={mode === "REGISTER"} onClick={() => { setMode("REGISTER"); setAuthStatus("IDLE"); }}>회원가입</button>
          </div>
          <form className="auth-form" onSubmit={(event) => void submitCredential(event)}>
            {mode === "REGISTER" && <label className="field"><span>닉네임</span><input name="nickname" type="text" autoComplete="nickname" minLength={2} maxLength={20} required /><small>내 정보와 로그인 상태에 표시됩니다.</small></label>}
            <label className="field"><span>이메일</span><input name="email" type="email" autoComplete="email" maxLength={254} required /></label>
            <label className="field"><span>비밀번호</span><input name="password" type="password" autoComplete={mode === "LOGIN" ? "current-password" : "new-password"} minLength={12} maxLength={128} required /><small>12자 이상 입력해 주세요.</small></label>
            {mode === "REGISTER" && <fieldset className="signup-consents"><legend>개인정보와 데이터 권리</legend><label><input name="requiredPrivacyAccepted" type="checkbox" required /><span><strong>[필수] 개인정보 처리와 데이터 권리 안내 동의</strong><small>서비스 제공, 계정 관리와 데이터 열람·삭제 요청 처리를 위한 안내입니다. <a href="/privacy" target="_blank">내용 보기</a></small></span></label><p>선택 동의</p><label><input name="SEARCH_HISTORY" type="checkbox" /><span>검색 기록 저장</span></label><label><input name="PRECISE_LOCATION" type="checkbox" /><span>정확한 저장 장소</span></label><label><input name="PRODUCT_ANALYTICS" type="checkbox" /><span>제품 개선 분석</span></label><label><input name="ROUTING_FEEDBACK" type="checkbox" /><span>경로 의견 활용</span></label><small className="consent-help">선택 항목은 동의하지 않아도 가입할 수 있고, 언제든 내 정보에서 바꿀 수 있어요.</small></fieldset>}
            <button className="primary-button" type="submit" disabled={authStatus === "SENDING"}>{authStatus === "SENDING" ? "확인 중…" : mode === "LOGIN" ? "로그인" : "계정 만들기"}</button>
            {authStatus === "INVALID" && <p className="auth-error" role="alert">이메일 또는 비밀번호가 올바르지 않습니다.</p>}
            {authStatus === "INVALID_INPUT" && <p className="auth-error" role="alert">입력 내용을 확인해 주세요. 닉네임은 2~20자, 비밀번호는 12자 이상이어야 합니다.</p>}
            {authStatus === "PRIVACY_REQUIRED" && <p className="auth-error" role="alert">필수 개인정보 안내에 동의해야 계정을 만들 수 있습니다.</p>}
            {authStatus === "UPDATE_REQUIRED" && <div className="auth-error auth-recovery" role="alert"><span>앱 버전이 서버와 맞지 않습니다. 새 버전을 불러온 뒤 다시 가입해 주세요.</span><button type="button" onClick={() => window.location.reload()}>새 버전 불러오기</button></div>}
            {authStatus === "SECURITY_EXPIRED" && <div className="auth-error auth-recovery" role="alert"><span>보안 확인이 만료되었습니다. 화면을 새로고침한 뒤 다시 시도해 주세요.</span><button type="button" onClick={() => window.location.reload()}>새로고침</button></div>}
            {authStatus === "RATE_LIMITED" && <p className="auth-error" role="alert">가입 요청이 많습니다. 1분 뒤 다시 시도해 주세요.</p>}
            {authStatus === "OFFLINE" && <p className="auth-error" role="alert">인터넷 연결을 확인한 뒤 다시 시도해 주세요.</p>}
            {authStatus === "DUPLICATE" && <p className="auth-error" role="alert">이미 가입된 이메일입니다. 로그인해 주세요.</p>}
            {authStatus === "FAILED" && <p className="auth-error" role="alert">지금은 계정 요청을 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.</p>}
          </form>
        </div>
      )}
      <div className="account-session-actions">
        {status === "SIGNED_OUT" && <button className="primary-button" type="button" onClick={() => void startGuestSession()}>게스트 세션 시작</button>}
        {status === "READY" && <button className="secondary-button" type="button" onClick={() => void signOut()}>{session?.subjectType === "USER" ? "로그아웃" : "게스트 세션 종료"}</button>}
        {status === "LOADING" && <p role="status">세션을 확인하는 중…</p>}
        {status === "FAILED" && <p className="degraded-notice" role="alert">로그인 상태를 확인할 수 없습니다. 길찾기는 로그인 없이 계속 사용할 수 있습니다.</p>}
        <a className="primary-link" href="/privacy">개인정보와 데이터 권리 확인</a>
      </div>
    </PageFrame>
  );
}

export function MePage() {
  const [session, setSession] = useState<SessionContext | null>(null);
  useEffect(() => { void inspectCurrentSession().then(setSession).catch(() => setSession(null)); }, []);
  return (
    <PageFrame eyebrow="내 정보" title={session?.subjectType === "USER" ? session.nickname ?? "82TA 사용자" : "내 정보"}>
      <div className="me-grid">
        <a href="/preferences"><strong>이동 선호</strong><span>예산·도보·환승 기본값</span></a>
        <a href="/places"><strong>저장 장소</strong><span>민감 위치 관리</span></a>
        <a href="/support"><strong>지원 범위</strong><span>현재 기능과 제한</span></a>
        <a href="/privacy"><strong>개인정보</strong><span>위치·데이터 받기·삭제</span></a>
        <a href="/account"><strong>계정</strong><span>로그인·회원가입·세션 관리</span></a>
      </div>
    </PageFrame>
  );
}

export function PrivacyPage() {
  const [consents, setConsents] = useState<ConsentRecord[] | null>(null);
  const [exportJob, setExportJob] = useState<DataRightsJob | null>(null);
  const [deletionJob, setDeletionJob] = useState<DataRightsJob | null>(null);
  const [status, setStatus] = useState<"IDLE" | "SENDING" | "FAILED">("IDLE");
  const documentVersion = import.meta.env.VITE_PRIVACY_DOCUMENT_VERSION;

  async function reloadConsents() {
    const { data, response } = await listConsents();
    if (!response.ok || data === undefined) throw new Error("Consent unavailable");
    setConsents(data.items);
  }

  useEffect(() => { void reloadConsents().catch(() => setStatus("FAILED")); }, []);

  async function setConsent(consentType: ConsentType, accepted: boolean) {
    if (documentVersion === undefined || documentVersion.trim().length === 0) return;
    setStatus("SENDING");
    try {
      const { response } = await recordConsent(consentType, { documentVersion, accepted });
      if (!response.ok) throw new Error("Consent update failed");
      await reloadConsents();
      setStatus("IDLE");
    } catch { setStatus("FAILED"); }
  }

  async function requestExport() {
    setStatus("SENDING");
    try {
      const { data, response } = await createDataExport();
      if (response.status !== 202 || data === undefined) throw new Error("Export request failed");
      setExportJob(data);
      setStatus("IDLE");
    } catch { setStatus("FAILED"); }
  }

  async function requestDeletion() {
    if (!window.confirm("계정과 관련 위치·저장 장소·검색 기록·동의·feedback 삭제를 요청할까요? 이 작업은 복구되지 않을 수 있습니다.")) return;
    setStatus("SENDING");
    try {
      const { data, response } = await createDataDeletion();
      if (response.status !== 202 || data === undefined) throw new Error("Deletion request failed");
      setDeletionJob(data);
      setStatus("IDLE");
    } catch { setStatus("FAILED"); }
  }

  async function refreshJob(job: DataRightsJob) {
    try {
      const result = job.type === "EXPORT" ? await getDataExport(job.jobId) : await getDataDeletion(job.jobId);
      if (!result.response.ok || result.data === undefined) throw new Error("Job unavailable");
      if (job.type === "EXPORT") setExportJob(result.data); else setDeletionJob(result.data);
    } catch { setStatus("FAILED"); }
  }

  useEffect(() => {
    const activeJobs = [exportJob, deletionJob].filter((job): job is DataRightsJob => job?.status === "PENDING" || job?.status === "RUNNING");
    if (activeJobs.length === 0 || status === "FAILED") return undefined;
    const timer = window.setTimeout(() => {
      void Promise.all(activeJobs.map((job) => refreshJob(job)));
    }, 3_000);
    return () => window.clearTimeout(timer);
  }, [deletionJob, exportJob, status]);

  const consentLabels: Readonly<Record<ConsentType, string>> = {
    SERVICE_PRIVACY: "개인정보 처리와 데이터 권리 안내",
    SEARCH_HISTORY: "검색 기록 저장",
    PRECISE_LOCATION: "정확한 저장 장소",
    PRODUCT_ANALYTICS: "제품 개선 분석",
    ROUTING_FEEDBACK: "경로 의견 활용",
  };

  return (
    <PageFrame eyebrow="개인정보" title="위치는 필요한 순간에만">
      <div className="privacy-grid">
        <article><h2>현재 위치</h2><p>브라우저 권한으로 한 번 읽고 현재 화면 상태에서만 사용합니다. 프론트 저장소와 로그에 좌표를 남기지 않습니다.</p></article>
        <article><h2>저장 장소와 기록</h2><p>로그인과 동의가 있는 경우에만 82TA 계정에 보관합니다. 길찾기 계산에는 계정 정보나 장소 별칭을 보내지 않습니다.</p></article>
        <article><h2>오프라인 저장</h2><p>앱을 여는 데 필요한 기본 파일만 기기에 보관합니다. 길찾기 결과와 계정 정보는 오프라인용으로 저장하지 않습니다.</p></article>
      </div>
      <section className="privacy-section" aria-labelledby="consent-title">
        <h2 id="consent-title">동의 관리</h2>
        {documentVersion === undefined || documentVersion.trim().length === 0 ? (
          <p className="degraded-notice">개인정보 안내 설정을 확인할 수 없어 동의 변경을 잠시 사용할 수 없습니다.</p>
        ) : consents === null ? <p role="status">동의 상태를 불러오는 중…</p> : (
          <ul className="consent-list">{(Object.keys(consentLabels) as ConsentType[]).map((type) => {
            const record = consents.find((item) => item.consentType === type);
            return <li key={type}><span><strong>{consentLabels[type]}</strong><small>{record === undefined ? "기록 없음" : `${record.documentVersion} · ${record.accepted ? "동의" : "거절"}`}</small></span>{type === "SERVICE_PRIVACY" ? <small>필수 · 계정 삭제로 종료</small> : <button className="secondary-button" type="button" disabled={status === "SENDING"} onClick={() => void setConsent(type, record?.accepted !== true)}>{record?.accepted === true ? "동의 철회" : "동의"}</button>}</li>;
          })}</ul>
        )}
      </section>
      <section className="privacy-section" aria-labelledby="rights-title">
        <h2 id="rights-title">데이터 권리</h2>
        <div className="rights-actions">
          <button className="primary-button" type="button" disabled={status === "SENDING" || exportJob?.status === "PENDING" || exportJob?.status === "RUNNING"} onClick={() => void requestExport()}>내 데이터 받기</button>
          <button className="danger-button" type="button" disabled={status === "SENDING" || deletionJob?.status === "PENDING" || deletionJob?.status === "RUNNING"} onClick={() => void requestDeletion()}>계정 데이터 삭제 요청</button>
        </div>
        {[exportJob, deletionJob].filter((job): job is DataRightsJob => job !== null).map((job) => {
          const expiry = job.downloadExpiresAt == null ? null : new Date(job.downloadExpiresAt);
          const downloadUrl = job.status === "COMPLETE" && expiry !== null && !Number.isNaN(expiry.getTime()) && expiry.getTime() > Date.now()
            ? safeDownloadUrl(job.downloadUrl)
            : null;
          const stateLabel = job.status === "PENDING" ? "요청 접수" : job.status === "RUNNING" ? "처리 중" : job.status === "COMPLETE" ? "완료" : "실패";
          return <div className="job-status" key={job.jobId}><strong>{job.type === "EXPORT" ? "데이터 받기" : "삭제"} · {stateLabel}</strong><span>요청 {new Date(job.requestedAt).toLocaleString("ko-KR")}</span>{(job.status === "PENDING" || job.status === "RUNNING") && <span role="status">진행 상태를 자동으로 다시 확인합니다.</span>}<button className="secondary-button" type="button" onClick={() => void refreshJob(job)}>상태 새로고침</button>{job.type === "EXPORT" && job.status === "COMPLETE" && downloadUrl !== null && <a href={downloadUrl} rel="noopener noreferrer">만료 전 다운로드</a>}{job.type === "EXPORT" && job.status === "COMPLETE" && downloadUrl === null && <span>다운로드 기간이 지났습니다. 다시 요청해 주세요.</span>}{job.status === "FAILED" && <span>요청을 완료하지 못했습니다. 고객지원에서 상태를 확인해 주세요.</span>}</div>;
        })}
      </section>
      {status === "FAILED" && <p role="alert">개인정보 요청을 완료하지 못했습니다. 로그인 상태를 확인한 뒤 다시 시도해 주세요.</p>}
    </PageFrame>
  );
}
