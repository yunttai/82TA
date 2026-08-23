import { useEffect, useRef, useState } from "react";

import { HomeMap } from "../features/home/HomeMap";
import { PwaStatus } from "../features/pwa/PwaStatus";
import { ResultPanel } from "../features/route-results/ResultPanel";
import { SearchForm } from "../features/route-search/SearchForm";
import { useRouteSearch } from "../features/route-search/useRouteSearch";
import { getPreferences, getPublicCapabilities, type PublicCapabilities, type UserPreferences } from "../shared/api/publicService";
import { inspectCurrentSession } from "../shared/session/sessionMemory";
import {
  AccountPage,
  FavoritesPage,
  HistoryPage,
  MePage,
  PreferencesPage,
  PrivacyPage,
  SavedPlacesPage,
  StoredSearchPage,
  SupportPage,
} from "../pages/ServicePages";

const navigation = [
  ["/", "홈", "home"],
  ["/search", "길찾기", "route"],
  ["/history", "기록", "history"],
  ["/favorites", "즐겨찾기", "favorite"],
  ["/me", "내 정보", "person"],
] as const;

function NavigationIcon({ name }: { name: (typeof navigation)[number][2] | "account" }) {
  const paths = {
    home: <><path d="m3.5 11 8.5-7 8.5 7" /><path d="M5.5 10v10h13V10M9.5 20v-6h5v6" /></>,
    route: <><circle cx="6" cy="18" r="2" /><circle cx="18" cy="6" r="2" /><path d="M8 18h3a3 3 0 0 0 3-3V9a3 3 0 0 1 3-3h-1" /></>,
    history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5M12 7v5l3 2" /></>,
    favorite: <path d="M12 20.2 4.7 13A4.8 4.8 0 0 1 11.5 6l.5.6.5-.6a4.8 4.8 0 0 1 6.8 6.9Z" />,
    person: <><circle cx="12" cy="8" r="3.5" /><path d="M5 20a7 7 0 0 1 14 0" /></>,
    account: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="9" r="2.5" /><path d="M7.5 18a5 5 0 0 1 9 0" /></>,
  } as const;
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{paths[name]}</svg>;
}

function quickBudgetFromUrl(): number | undefined {
  const raw = new URLSearchParams(window.location.search).get("budget");
  if (raw === null || !/^\d+$/.test(raw)) return undefined;
  const budget = Number(raw);
  return Number.isSafeInteger(budget) && budget >= 0 && budget <= 500_000 ? budget : undefined;
}

function SearchPage() {
  const { state, search, retry, reset } = useRouteSearch();
  const [capabilities, setCapabilities] = useState<PublicCapabilities | null>(null);
  const [capabilitiesFailed, setCapabilitiesFailed] = useState(false);
  const [initialPreferences, setInitialPreferences] = useState<UserPreferences | null>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const busy = state.phase === "VALIDATING" || state.phase === "SEARCHING";
  const hasResponse = "response" in state && state.response !== null;
  const quickBudget = quickBudgetFromUrl();

  useEffect(() => {
    void getPublicCapabilities().then(({ data, response }) => {
      if (!response.ok || data === undefined) setCapabilitiesFailed(true);
      else setCapabilities(data);
    }).catch(() => setCapabilitiesFailed(true));
  }, []);

  useEffect(() => {
    void inspectCurrentSession().then(async (session) => {
      if (session?.subjectType !== "USER") return;
      const { data, response } = await getPreferences();
      if (response.ok && data !== undefined) setInitialPreferences(data);
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    const handleOnline = () => setOnline(true);
    const handleOffline = () => setOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return (
    <>
      <main id="main-content" className="content">
        <header className={`search-intro${hasResponse ? " search-intro-results" : ""}`}>
          <p className="eyebrow">예산 맞춤 길찾기</p>
          <h1>{hasResponse ? "추천 경로를 찾았어요" : "어디로 갈까요?"}</h1>
          {!hasResponse && <p>예산 안에서 더 빠르고 안정적인 이동을 찾아드려요.</p>}
        </header>
        {hasResponse && "request" in state && (
          <section className="search-summary" aria-label="검색 조건 요약">
            <div>
              <strong>{state.request.origin.displayName}</strong>
              <span aria-hidden="true">→</span>
              <strong>{state.request.destination.displayName}</strong>
            </div>
            <p>택시비 상한 {state.request.taxiBudget.maxAmount.toLocaleString("ko-KR")}원</p>
            <button type="button" onClick={reset}>조건 수정</button>
          </section>
        )}
        <section className="search-card" aria-labelledby="search-title" hidden={hasResponse}>
          <div className="search-card-heading">
            <span className="search-card-mark" aria-hidden="true">↗</span>
            <div>
              <h2 id="search-title">경로 검색</h2>
              <p>장소와 사용할 택시비를 입력하세요.</p>
            </div>
          </div>
          {capabilitiesFailed && <p className="degraded-notice" role="status">현재 기능 지원 범위를 확인할 수 없습니다. 좌석 위험 회피와 택시 연결 선택은 잠갔습니다.</p>}
          <SearchForm busy={busy} offline={!online} errors={state.errors} capabilities={capabilities} initialPreferences={initialPreferences} {...(quickBudget === undefined ? {} : { initialTaxiBudget: quickBudget })} onSubmit={search} />
        </section>

        {state.phase === "SEARCHING" && (
          <section className="search-progress" aria-live="polite" aria-busy="true">
            <span className="progress-mark" aria-hidden="true">82</span>
            <div><h2>가능한 이동 조합을 비교하고 있습니다</h2><p>택시비 상한, P50·P90 도착시간, 환승과 지원 정보를 함께 확인합니다.</p></div>
          </section>
        )}

        {state.phase !== "IDLE" && state.phase !== "VALIDATING" && state.phase !== "SEARCHING" && (
          <ResultPanel
            phase={state.phase}
            response={state.response}
            problem={state.problem}
            {...("request" in state && state.request.taxiBudget.strict ? { strictTaxiBudgetKrw: state.request.taxiBudget.maxAmount } : {})}
            {...(online ? { onRetry: retry } : {})}
            onRestart={reset}
          />
        )}
      </main>
    </>
  );
}

function CurrentPage({ path }: { path: string }) {
  const busMatch = path.match(/^\/searches\/([^/]+)\/routes\/([^/]+)\/bus\/([^/]+)$/);
  if (busMatch !== null) return <main id="main-content" className="content page-content"><StoredSearchPage searchId={decodeURIComponent(busMatch[1] ?? "")} routeId={decodeURIComponent(busMatch[2] ?? "")} legId={decodeURIComponent(busMatch[3] ?? "")} /></main>;
  const routeMatch = path.match(/^\/searches\/([^/]+)\/routes\/([^/]+)$/);
  if (routeMatch !== null) return <main id="main-content" className="content page-content"><StoredSearchPage searchId={decodeURIComponent(routeMatch[1] ?? "")} routeId={decodeURIComponent(routeMatch[2] ?? "")} /></main>;
  const searchMatch = path.match(/^\/searches\/([^/]+)$/);
  if (searchMatch !== null) return <main id="main-content" className="content page-content"><StoredSearchPage searchId={decodeURIComponent(searchMatch[1] ?? "")} /></main>;

  switch (path) {
    case "/": return <HomeMap />;
    case "/search": return <SearchPage />;
    case "/history": return <main id="main-content" className="content page-content"><HistoryPage /></main>;
    case "/places":
    case "/saved-places": return <main id="main-content" className="content page-content"><SavedPlacesPage /></main>;
    case "/favorites": return <main id="main-content" className="content page-content"><FavoritesPage /></main>;
    case "/preferences": return <main id="main-content" className="content page-content"><PreferencesPage /></main>;
    case "/support": return <main id="main-content" className="content page-content"><SupportPage /></main>;
    case "/me": return <main id="main-content" className="content page-content"><MePage /></main>;
    case "/account": return <main id="main-content" className="content page-content"><AccountPage /></main>;
    case "/privacy": return <main id="main-content" className="content page-content"><PrivacyPage /></main>;
    default: return <main id="main-content" className="content page-content"><section className="empty-state"><h1 className="page-title">페이지를 찾을 수 없습니다</h1><a href="/search">길찾기로 이동</a></section></main>;
  }
}

function navigationActive(path: string, href: (typeof navigation)[number][0]): boolean {
  if (href === "/search") return path === "/search" || path.startsWith("/searches/");
  return path === href;
}

export function App() {
  const [path, setPath] = useState(() => window.location.pathname.replace(/\/$/, "") || "/");
  const initialPath = useRef(true);

  useEffect(() => {
    const handlePopState = () => setPath(window.location.pathname.replace(/\/$/, "") || "/");
    const handleNavigation = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const link = target.closest("a");
      if (!(link instanceof HTMLAnchorElement) || link.target || link.download || link.getAttribute("rel") === "external") return;
      const destination = new URL(link.href, window.location.href);
      if (destination.origin !== window.location.origin || destination.hash || destination.pathname === window.location.pathname) return;
      event.preventDefault();
      window.history.pushState(null, "", destination);
      setPath(destination.pathname.replace(/\/$/, "") || "/");
    };

    window.addEventListener("popstate", handlePopState);
    document.addEventListener("click", handleNavigation);
    return () => {
      window.removeEventListener("popstate", handlePopState);
      document.removeEventListener("click", handleNavigation);
    };
  }, []);

  useEffect(() => {
    if (initialPath.current) {
      initialPath.current = false;
      return;
    }
    const main = document.getElementById("main-content");
    main?.setAttribute("tabindex", "-1");
    main?.focus({ preventScroll: true });
  }, [path]);

  return (
    <div className={`app-shell${path === "/" ? " app-shell-home" : ""}`}>
      <a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
      <header className="topbar">
        <a className="brand" href="/" aria-label="82TA 홈"><span aria-hidden="true">82</span><b>TA</b></a>
        <nav className="desktop-nav" aria-label="주요 메뉴">
          {navigation.map(([href, label, icon]) => <a key={href} href={href} aria-current={navigationActive(path, href) ? "page" : undefined}><NavigationIcon name={icon} /><span>{label}</span></a>)}
        </nav>
        <a className="account-link" href="/account"><NavigationIcon name="account" /><span>계정</span></a>
      </header>
      <PwaStatus />
      <CurrentPage path={path} />
      {path !== "/" && <footer>
        <p>82TA는 경로를 추천하며 택시 호출·버스 좌석을 보장하지 않습니다.</p>
        <nav aria-label="정책"><a href="/support">지원 범위</a><a href="/privacy">개인정보</a></nav>
      </footer>}
      <nav className="bottom-nav" aria-label="모바일 주요 메뉴">
        {navigation.map(([href, label, icon]) => <a key={href} href={href} aria-current={navigationActive(path, href) ? "page" : undefined}><NavigationIcon name={icon} /><span>{label}</span></a>)}
      </nav>
    </div>
  );
}
