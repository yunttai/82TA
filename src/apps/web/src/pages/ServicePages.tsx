import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { PlaceField } from "../features/place-search/PlaceField";
import { ResultPanel } from "../features/route-results/ResultPanel";
import {
  createFavoriteJourney,
  createDataDeletion,
  createDataExport,
  createGuestSession,
  createSavedPlace,
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
  revokeCurrentSession,
  recordConsent,
  updatePreferences,
  updateFavoriteJourney,
  updateSavedPlace,
  type FavoriteJourney,
  type ConsentRecord,
  type ConsentType,
  type DataRightsJob,
  type PlaceRef,
  type PublicCapabilities,
  type PublicRouteSearchResponse,
  type SavedPlace,
  type SessionContext,
  type UserPreferences,
} from "../shared/api/publicService";
import {
  clearSessionMemory,
  currentGuestToken,
  inspectCurrentSession,
  rememberGuestSession,
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
  if (failed) return <p className="degraded-notice" role="status">계정 API에 연결할 수 없습니다. 로그인 또는 Backend 준비 상태를 확인해 주세요.</p>;
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

export function HistoryPage() {
  const [items, setItems] = useState<PublicRouteSearchResponse[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    void listRouteSearches().then(({ data, response }) => {
      if (!response.ok || data === undefined) setFailed(true);
      else setItems(data.items);
    }).catch(() => setFailed(true));
  }, []);

  return (
    <PageFrame eyebrow="내 이동" title="검색 기록">
      <p className="page-lead">기록 저장에 동의한 로그인 사용자에게만 표시됩니다.</p>
      {items === null || items.length === 0 ? <LoadMessage failed={failed} empty={items?.length === 0} /> : (
        <ul className="resource-list">
          {items.map((item) => (
            <li key={item.searchId}>
              <div><strong>{item.status}</strong><span>{new Date(item.generatedAt).toLocaleString("ko-KR")}</span></div>
              <span>{item.history === undefined ? "저장 정보 확인 불가" : `${item.history.saved ? "기록 저장됨" : "기록 저장 안 함"} · ${item.history.ownerKind === "USER" ? "로그인 사용자" : "게스트"}`}</span>
              {item.history?.retainedUntil != null && <span>보관 기한 {new Date(item.history.retainedUntil).toLocaleString("ko-KR")}</span>}
              {item.status === "EXPIRED" || new Date(item.expiresAt).getTime() <= Date.now()
                ? <a href="/">만료됨 · 다시 검색</a>
                : <a href={`/searches/${encodeURIComponent(item.searchId)}`}>저장 결과 확인</a>}
            </li>
          ))}
        </ul>
      )}
    </PageFrame>
  );
}

export function StoredSearchPage({ searchId, routeId, legId }: { searchId: string; routeId?: string; legId?: string }) {
  const [response, setResponse] = useState<PublicRouteSearchResponse | null>(null);
  const [status, setStatus] = useState<"LOADING" | "NOT_FOUND" | "FORBIDDEN" | "FAILED">("LOADING");
  useEffect(() => {
    void getRouteSearch(searchId, currentGuestToken()).then(({ data, error, response: rawResponse }) => {
      if (data !== undefined) { setResponse(data); return; }
      if (rawResponse.status === 404) setStatus("NOT_FOUND");
      else if (rawResponse.status === 403) setStatus("FORBIDDEN");
      else {
        void error;
        setStatus("FAILED");
      }
    }).catch(() => setStatus("FAILED"));
  }, [searchId]);

  if (response === null) {
    const message = status === "LOADING" ? "저장 결과를 불러오는 중…" : status === "NOT_FOUND" ? "검색 결과를 찾을 수 없습니다." : status === "FORBIDDEN" ? "이 검색 결과에 접근할 수 없습니다." : "검색 결과를 불러오지 못했습니다.";
    return <PageFrame eyebrow="저장 결과" title={message}><a href="/">새 경로 검색</a></PageFrame>;
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
      <ResultPanel phase={new Date(response.expiresAt).getTime() <= Date.now() ? "EXPIRED" : response.status} response={response} problem={null} {...(routeId === undefined ? {} : { initialRouteId: routeId })} {...(legId === undefined ? {} : { initialLegId: legId })} />
    </div>
  );
}

export function SavedPlacesPage() {
  const [items, setItems] = useState<SavedPlace[] | null>(null);
  const [place, setPlace] = useState<PlaceRef | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"IDLE" | "SAVING" | "FAILED">("IDLE");

  async function reload() {
    const { data, response } = await listSavedPlaces();
    if (!response.ok || data === undefined) throw new Error("Saved places unavailable");
    setItems(data);
  }

  useEffect(() => { void reload().catch(() => setStatus("FAILED")); }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (place === null) return;
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
      <p className="page-lead">정확한 위치는 민감정보로 취급되며 Service 계정 경계 안에서만 저장됩니다.</p>
      <form className="resource-form" onSubmit={(event) => void submit(event)}>
        <label className="field"><span>별칭</span><input name="label" maxLength={50} placeholder="집, 학교, 회사" required /></label>
        <PlaceField label="장소 검색" value={query} onLabelChange={setQuery} onPlaceSelected={(selected) => { setPlace(selected); setQuery(selected.displayName); }} />
        <button className="primary-button" type="submit" disabled={place === null || status === "SAVING"}>민감 장소로 저장</button>
        {status === "FAILED" && <p role="alert">저장 장소 API를 사용할 수 없습니다.</p>}
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
  const [failed, setFailed] = useState(false);

  async function reload() {
    const [favoriteResult, placeResult] = await Promise.all([listFavoriteJourneys(), listSavedPlaces()]);
    if (!favoriteResult.response.ok || favoriteResult.data === undefined || !placeResult.response.ok || placeResult.data === undefined) {
      throw new Error("Favorites unavailable");
    }
    setFavorites(favoriteResult.data);
    setPlaces(placeResult.data);
  }

  useEffect(() => { void reload().catch(() => setFailed(true)); }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const nickname = data.get("nickname");
    const originSavedPlaceId = data.get("originSavedPlaceId");
    const destinationSavedPlaceId = data.get("destinationSavedPlaceId");
    if (typeof nickname !== "string" || typeof originSavedPlaceId !== "string" || typeof destinationSavedPlaceId !== "string") return;
    try {
      const result = await createFavoriteJourney({ nickname, originSavedPlaceId, destinationSavedPlaceId, defaultConstraints: {} });
      if (!result.response.ok) throw new Error("Favorite save failed");
      await reload();
    } catch {
      setFailed(true);
    }
  }

  async function rename(item: FavoriteJourney) {
    const nickname = window.prompt("새 여정 이름", item.nickname)?.trim();
    if (nickname === undefined || nickname.length === 0 || nickname === item.nickname) return;
    try {
      const result = await updateFavoriteJourney(item.id, { nickname });
      if (!result.response.ok) throw new Error("Favorite update failed");
      await reload();
    } catch { setFailed(true); }
  }

  async function remove(item: FavoriteJourney) {
    if (!window.confirm(`‘${item.nickname}’ 즐겨찾기를 삭제할까요?`)) return;
    try {
      const result = await deleteFavoriteJourney(item.id);
      if (result.response.status !== 204) throw new Error("Favorite delete failed");
      await reload();
    } catch { setFailed(true); }
  }

  return (
    <PageFrame eyebrow="내 이동" title="즐겨찾는 여정">
      <p className="page-lead">저장 장소 두 곳을 연결해 자주 쓰는 여정을 만듭니다.</p>
      {places.length >= 2 ? (
        <form className="resource-form compact-form" onSubmit={(event) => void submit(event)}>
          <label className="field"><span>여정 이름</span><input name="nickname" maxLength={100} required /></label>
          <label className="field"><span>출발 장소</span><select name="originSavedPlaceId">{places.map((place) => <option key={place.id} value={place.id}>{place.label}</option>)}</select></label>
          <label className="field"><span>도착 장소</span><select name="destinationSavedPlaceId">{places.map((place) => <option key={place.id} value={place.id}>{place.label}</option>)}</select></label>
          <button className="primary-button" type="submit">즐겨찾기 저장</button>
        </form>
      ) : <p className="degraded-notice">즐겨찾기를 만들려면 저장 장소가 두 개 이상 필요합니다.</p>}
      {favorites === null || favorites.length === 0 ? <LoadMessage failed={failed} empty={favorites?.length === 0} /> : (
        <ul className="resource-list">{favorites.map((item) => <li key={item.id}><strong>{item.nickname}</strong><span>{new Date(item.createdAt).toLocaleDateString("ko-KR")}</span><div className="item-actions"><button type="button" onClick={() => void rename(item)}>이름 수정</button><button type="button" onClick={() => void remove(item)}>삭제</button></div></li>)}</ul>
      )}
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
          <p className="resource-meta">서버 설정 version {preferences.version ?? "확인 불가"}{preferences.updatedAt === undefined ? "" : ` · ${new Date(preferences.updatedAt).toLocaleString("ko-KR")} 갱신`}</p>
          {status === "DONE" && <p role="status">선호를 저장했습니다.</p>}
          {status === "CONFLICT" && <div className="degraded-notice" role="alert"><p>다른 기기에서 선호가 변경되었습니다. 자동으로 덮어쓰지 않습니다.</p><button className="secondary-button" type="button" onClick={() => void reloadPreferences().catch(() => setStatus("FAILED"))}>서버 최신값 불러오기</button></div>}
          {status === "FAILED" && <p role="alert">선호 API를 사용할 수 없습니다.</p>}
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
      <p className="page-lead">지원 여부와 정보 공백을 숨기지 않습니다. 버스 좌석 엔진은 Routing 팀 결과를 Service가 표시만 합니다.</p>
      {support === null ? <LoadMessage failed={failed} empty={false} /> : (
        <>
          <p className="coverage-chip">Bus Intelligence: {support.busIntelligenceCoverage ?? "UNKNOWN"}</p>
          <ul className="capability-grid" aria-label="지역 지원">
            <li><span>출발 지역</span><strong>{support.region?.originSupported === true ? "지원" : support.region?.originSupported === false ? "미지원" : "확인 불가"}</strong></li>
            <li><span>도착 지역</span><strong>{support.region?.destinationSupported === true ? "지원" : support.region?.destinationSupported === false ? "미지원" : "확인 불가"}</strong></li>
          </ul>
          <ul className="capability-grid">{Object.entries(support.features).map(([name, enabled]) => (
            <li key={name}><span>{featureLabels[name] ?? "새 지원 항목"}</span><strong>{enabled === true ? "지원" : enabled === false ? "미지원" : "확인 중"}</strong></li>
          ))}</ul>
          {support.degraded.length > 0 && <div className="degraded-notice"><strong>현재 제한</strong><p>일부 기능이 제한되어 있습니다. 검색 결과의 warning과 각 기능 상태를 확인해 주세요.</p></div>}
        </>
      )}
    </PageFrame>
  );
}

export function AccountPage() {
  const [session, setSession] = useState<SessionContext | null>(null);
  const [guestToken, setGuestToken] = useState<string | undefined>(currentGuestToken());
  const [status, setStatus] = useState<"LOADING" | "READY" | "SIGNED_OUT" | "FAILED">("LOADING");

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

  return (
    <PageFrame eyebrow="계정" title="게스트로 바로 사용">
      <p className="page-lead">경로 검색은 로그인 없이 사용할 수 있습니다. 게스트 credential은 현재 page memory에서만 유지하고 URL·localStorage·로그에 넣지 않습니다.</p>
      {session !== null && <div className="coverage-chip">{session.subjectType === "USER" ? "로그인 사용자" : "게스트"} · {new Date(session.expiresAt).toLocaleString("ko-KR")}까지</div>}
      {status === "SIGNED_OUT" && <button className="primary-button" type="button" onClick={() => void startGuestSession()}>게스트 세션 시작</button>}
      {status === "READY" && <button className="secondary-button" type="button" onClick={() => void signOut()}>현재 세션 종료</button>}
      {status === "LOADING" && <p role="status">세션을 확인하는 중…</p>}
      {status === "FAILED" && <p className="degraded-notice" role="alert">세션 Backend를 사용할 수 없습니다. guest route search는 계속 사용할 수 있습니다.</p>}
      <div className="degraded-notice"><strong>사용자 로그인 연동 대기</strong><p>현재 계약에는 guest/session 조회·종료는 있지만 사용자 로그인 생성 방식은 정의되지 않았습니다.</p></div>
      <a className="primary-link" href="/privacy">개인정보와 데이터 권리 확인</a>
    </PageFrame>
  );
}

export function MePage() {
  return (
    <PageFrame eyebrow="내 정보" title="설정과 데이터">
      <div className="me-grid">
        <a href="/preferences"><strong>이동 선호</strong><span>예산·도보·환승 기본값</span></a>
        <a href="/places"><strong>저장 장소</strong><span>민감 위치 관리</span></a>
        <a href="/support"><strong>지원 범위</strong><span>현재 기능과 제한</span></a>
        <a href="/privacy"><strong>개인정보</strong><span>위치·삭제·export 상태</span></a>
        <a href="/account"><strong>계정</strong><span>guest와 로그인 준비 상태</span></a>
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
    SEARCH_HISTORY: "검색 기록 저장",
    PRECISE_LOCATION: "정확한 저장 장소",
    PRODUCT_ANALYTICS: "제품 개선 분석",
    ROUTING_FEEDBACK: "경로 의견 활용",
  };

  return (
    <PageFrame eyebrow="개인정보" title="위치는 필요한 순간에만">
      <div className="privacy-grid">
        <article><h2>현재 위치</h2><p>브라우저 권한으로 한 번 읽고 현재 화면 상태에서만 사용합니다. 프론트 저장소와 로그에 좌표를 남기지 않습니다.</p></article>
        <article><h2>저장 장소와 기록</h2><p>로그인·동의가 있는 경우 Service Backend가 관리합니다. Routing에는 사용자 identity나 장소 별칭을 보내지 않습니다.</p></article>
        <article><h2>오프라인 캐시</h2><p>앱 shell과 정적 자산만 캐시합니다. `/api/` 응답과 계정 데이터는 Service Worker가 캐시하지 않습니다.</p></article>
      </div>
      <section className="privacy-section" aria-labelledby="consent-title">
        <h2 id="consent-title">선택 동의</h2>
        {documentVersion === undefined || documentVersion.trim().length === 0 ? (
          <p className="degraded-notice">배포 환경의 개인정보 문서 version이 설정되지 않아 동의 변경을 잠갔습니다.</p>
        ) : consents === null ? <p role="status">동의 상태를 불러오는 중…</p> : (
          <ul className="consent-list">{(Object.keys(consentLabels) as ConsentType[]).map((type) => {
            const record = consents.find((item) => item.consentType === type);
            return <li key={type}><span><strong>{consentLabels[type]}</strong><small>{record === undefined ? "기록 없음" : `${record.documentVersion} · ${record.accepted ? "동의" : "거절"}`}</small></span><button className="secondary-button" type="button" disabled={status === "SENDING"} onClick={() => void setConsent(type, record?.accepted !== true)}>{record?.accepted === true ? "동의 철회" : "동의"}</button></li>;
          })}</ul>
        )}
      </section>
      <section className="privacy-section" aria-labelledby="rights-title">
        <h2 id="rights-title">데이터 권리</h2>
        <div className="rights-actions">
          <button className="primary-button" type="button" disabled={status === "SENDING" || exportJob?.status === "PENDING" || exportJob?.status === "RUNNING"} onClick={() => void requestExport()}>내 데이터 export 요청</button>
          <button className="danger-button" type="button" disabled={status === "SENDING" || deletionJob?.status === "PENDING" || deletionJob?.status === "RUNNING"} onClick={() => void requestDeletion()}>내 Service 데이터 삭제 요청</button>
        </div>
        {[exportJob, deletionJob].filter((job): job is DataRightsJob => job !== null).map((job) => {
          const expiry = job.downloadExpiresAt == null ? null : new Date(job.downloadExpiresAt);
          const downloadUrl = job.status === "COMPLETE" && expiry !== null && !Number.isNaN(expiry.getTime()) && expiry.getTime() > Date.now()
            ? safeDownloadUrl(job.downloadUrl)
            : null;
          const stateLabel = job.status === "PENDING" ? "요청 접수" : job.status === "RUNNING" ? "처리 중" : job.status === "COMPLETE" ? "완료" : "실패";
          return <div className="job-status" key={job.jobId}><strong>{job.type === "EXPORT" ? "Export" : "삭제"} · {stateLabel}</strong><span>요청 {new Date(job.requestedAt).toLocaleString("ko-KR")}</span>{(job.status === "PENDING" || job.status === "RUNNING") && <span role="status">서버 상태를 자동으로 다시 확인합니다.</span>}<button className="secondary-button" type="button" onClick={() => void refreshJob(job)}>상태 새로고침</button>{job.type === "EXPORT" && job.status === "COMPLETE" && downloadUrl !== null && <a href={downloadUrl} rel="noopener noreferrer">만료 전 다운로드</a>}{job.type === "EXPORT" && job.status === "COMPLETE" && downloadUrl === null && <span>다운로드가 만료되었거나 안전한 주소를 확인할 수 없어 새 export가 필요합니다.</span>}{job.status === "FAILED" && <span>요청을 완료하지 못했습니다. 고객지원에서 상태를 확인해 주세요.</span>}</div>;
        })}
      </section>
      {status === "FAILED" && <p role="alert">개인정보 API 요청을 완료하지 못했습니다. 로그인 상태와 Backend를 확인해 주세요.</p>}
    </PageFrame>
  );
}
