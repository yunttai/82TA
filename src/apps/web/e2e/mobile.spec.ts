import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import canonicalResponse from "../../../contracts/openapi/examples/public-route-search-response.json" with { type: "json" };

const guestToken = "guest_e2e_0123456789abcdef0123456789abcdef";

function commercializeRoute(route: typeof canonicalResponse.recommendations.fastest) {
  return {
    ...route,
    legs: route.legs.map((leg, index) => ({
      ...leg,
      from: index === 0 ? { ...leg.from, name: "Origin" } : leg.from,
      to: index === route.legs.length - 1 ? { ...leg.to, name: "Kakao Transit Destination" } : leg.to,
      transit: { ...leg.transit, routeLabel: "701", direction: "Kakao Transit Destination" },
    })),
  };
}

const commercialCanonicalResponse = {
  ...canonicalResponse,
  baseline: commercializeRoute(canonicalResponse.baseline),
  recommendations: {
    fastest: commercializeRoute(canonicalResponse.recommendations.fastest),
    stable: commercializeRoute(canonicalResponse.recommendations.stable),
    efficient: commercializeRoute(canonicalResponse.recommendations.efficient),
    publicTransitOnly: commercializeRoute(canonicalResponse.recommendations.publicTransitOnly),
  },
};

async function mockPublicApi(page: Page) {
  let authenticated = false;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/support/capabilities") {
      await route.fulfill({
        json: {
          region: { originSupported: true, destinationSupported: true },
          features: { taxiBridge: true, busSeatRisk: true, busEtaModel: true },
          busIntelligenceCoverage: "PARTIAL",
          degraded: [],
        },
      });
      return;
    }
    if (path === "/api/v1/health") {
      await route.fulfill({ json: { status: "ok" } });
      return;
    }
    if (path === "/api/v1/places/suggest") {
      const origin = new URL(request.url()).searchParams.get("query")?.includes("명지") === true;
      await route.fulfill({
        json: {
          items: [{
            displayName: origin ? "명지대학교 자연캠퍼스" : "판교역",
            coordinate: origin ? { lon: 127.187456, lat: 37.222345 } : { lon: 127.111159, lat: 37.394761 },
            provider: "KAKAO_LOCAL",
            providerPlaceId: origin ? "e2e-origin" : "e2e-destination",
          }],
        },
      });
      return;
    }
    if (path === "/api/v1/guest-sessions" && request.method() === "POST") {
      await route.fulfill({ status: 201, json: { guestToken, expiresAt: "2099-08-24T07:40:00+09:00" } });
      return;
    }
    if (path === "/api/v1/session" && request.method() === "GET") {
      if (authenticated) {
        await route.fulfill({ json: { subjectType: "USER", authenticated: true, expiresAt: "2099-08-24T07:40:00+09:00", email: "user@example.com", nickname: "팔이타" } });
      } else if (request.headers()["x-guest-token"] === guestToken) {
        await route.fulfill({ json: { subjectType: "GUEST", authenticated: false, expiresAt: "2099-08-24T07:40:00+09:00" } });
      } else {
        await route.fulfill({ status: 401, contentType: "application/problem+json", body: "{}" });
      }
      return;
    }
    if ((path === "/api/v1/auth/register" || path === "/api/v1/auth/login") && request.method() === "POST") {
      authenticated = true;
      await route.fulfill({ status: path.endsWith("register") ? 201 : 200, json: { subjectType: "USER", authenticated: true, expiresAt: "2099-08-24T07:40:00+09:00", email: "user@example.com", nickname: "팔이타" } });
      return;
    }
    if (path === "/api/v1/route-searches" && request.method() === "GET" && authenticated) {
      await route.fulfill({ json: { items: [] } });
      return;
    }
    if (path === "/api/v1/route-searches" && request.method() === "POST") {
      await route.fulfill({
        json: {
          ...commercialCanonicalResponse,
          status: "PARTIAL",
          expiresAt: "2099-08-23T07:42:05.421+09:00",
        },
      });
      return;
    }
    await route.fulfill({ status: 503, contentType: "application/problem+json", body: "{}" });
  });
}

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([{ name: "csrftoken", value: "e2e-csrf", domain: "127.0.0.1", path: "/", sameSite: "Lax" }]);
  await mockPublicApi(page);
});

test("guest can register and then open authenticated history", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/history");
  await expect(page.getByText("로그인이 필요한 기능이에요")).toBeVisible();
  await page.getByRole("link", { name: "로그인하기" }).click();
  const [authCard, guestButton, privacyLink] = await Promise.all([
    page.locator(".auth-card").boundingBox(),
    page.getByRole("button", { name: "게스트 세션 시작" }).boundingBox(),
    page.getByRole("link", { name: "개인정보와 데이터 권리 확인" }).boundingBox(),
  ]);
  expect(authCard).not.toBeNull();
  expect(guestButton).not.toBeNull();
  expect(privacyLink).not.toBeNull();
  expect(guestButton!.y - (authCard!.y + authCard!.height)).toBeGreaterThanOrEqual(20);
  expect(privacyLink!.y - (guestButton!.y + guestButton!.height)).toBeGreaterThanOrEqual(12);
  await page.getByRole("tab", { name: "회원가입" }).click();
  await page.getByLabel("닉네임").fill("팔이타");
  await page.getByLabel("이메일").fill("user@example.com");
  await page.getByLabel("비밀번호").fill("correct-horse-battery-staple");
  await page.getByLabel("[필수] 개인정보 처리와 데이터 권리 안내 동의").check();
  await page.getByRole("button", { name: "계정 만들기" }).click();
  await expect(page).toHaveURL(/\/history$/);
  await expect(page.getByText("아직 표시할 항목이 없습니다.")).toBeVisible();
});

test("iPhone account actions keep comfortable vertical spacing", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/account");
  const authCard = page.locator(".auth-card");
  const guestButton = page.getByRole("button", { name: "게스트 세션 시작" });
  const privacyLink = page.getByRole("link", { name: "개인정보와 데이터 권리 확인" });
  await expect(authCard).toBeVisible();
  await expect(guestButton).toBeVisible();
  await expect(privacyLink).toBeVisible();
  const [authBox, guestBox, privacyBox] = await Promise.all([
    authCard.boundingBox(),
    guestButton.boundingBox(),
    privacyLink.boundingBox(),
  ]);
  expect(authBox).not.toBeNull();
  expect(guestBox).not.toBeNull();
  expect(privacyBox).not.toBeNull();
  expect(guestBox!.y - (authBox!.y + authBox!.height)).toBeGreaterThanOrEqual(20);
  expect(privacyBox!.y - (guestBox!.y + guestBox!.height)).toBeGreaterThanOrEqual(12);
  expect(guestBox!.height).toBeGreaterThanOrEqual(48);
  expect(privacyBox!.height).toBeGreaterThanOrEqual(48);
});

test("mobile route search stays within the Public Service boundary", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto("/search");

  expect(await page.locator("body").innerText()).toContain("어디로 갈까요?");
  await expect(page.getByRole("navigation", { name: "모바일 주요 메뉴" })).toBeVisible();
  await expect(page.getByRole("link", { name: "길찾기" })).toHaveAttribute("aria-current", "page");
  await page.getByText("지도에서 직접 위치 선택").click();
  await expect(page.locator(".coordinate-map")).toBeVisible();
  await page.getByRole("combobox", { name: "출발지" }).fill("명지");
  await page.getByRole("option", { name: "명지대학교 자연캠퍼스" }).click();
  await page.getByRole("combobox", { name: "목적지" }).fill("판교");
  await page.getByRole("option", { name: "판교역" }).click();
  await page.getByRole("button", { name: "내 예산으로 경로 찾기" }).click();
  await expect(page.getByText("일부 정보 없이 계산한 결과입니다.")).toBeVisible();
  await expect(page.getByRole("region", { name: "경로 상세" })).toBeVisible();
  await expect(page.getByText(/에서 버스 .*승차/)).toBeVisible();
  await expect(page.getByText(/에서 하차/)).toBeVisible();
  expect(await page.locator("body").innerText()).not.toMatch(/P50|P90|ETA|어디서 타고, 어디서 갈아타는지|Origin|Destination|Kakao\s+Transit|Sanitized|SAN-R1|다음 ·/i);
  const resultOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(resultOverflow).toBeLessThanOrEqual(1);

  expect(requests.some((url) => new URL(url).pathname === "/api/v1/route-searches")).toBe(true);
  expect(requests.some((url) => /\/v1\/routes\/optimize/.test(new URL(url).pathname))).toBe(false);
});

test("320px layout has no horizontal page overflow and no serious accessibility violations", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/");
  const bottomNav = page.getByRole("navigation", { name: "모바일 주요 메뉴" });
  await expect(bottomNav).toHaveCSS("position", "fixed");
  await expect(page.getByRole("heading", { name: /예산은 지키고.*도착은 빠르게/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /길찾기 카드/ })).toHaveCount(0);
  await expect(bottomNav.getByRole("link", { name: "홈", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("link", { name: /어디로 갈까요/ })).toBeVisible();
  await expect(page.getByText("지도를 불러오지 못했어요")).toBeVisible();
  const sizes = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, content: document.documentElement.scrollWidth }));
  expect(sizes.content).toBeLessThanOrEqual(sizes.viewport);

  await bottomNav.getByRole("link", { name: "길찾기", exact: true }).click();
  await expect(page.getByText("세부 조건", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: "대중교통 사이 짧은 택시 이동 허용" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "검색 기록에 저장" })).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(2);
  const searchSizes = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, content: document.documentElement.scrollWidth }));
  expect(searchSizes.content).toBeLessThanOrEqual(searchSizes.viewport);

  await page.getByRole("combobox", { name: "출발지" }).fill("명지대학교");
  await page.getByRole("option", { name: "명지대학교 자연캠퍼스" }).click();
  await page.getByRole("combobox", { name: "목적지" }).fill("판교");
  await page.getByRole("option", { name: "판교역" }).click();
  await page.getByRole("button", { name: "내 예산으로 경로 찾기" }).click();
  await expect(page.getByRole("region", { name: "경로 상세" })).toBeVisible();
  const resultBounds = await page.locator(".results, .results-workspace, .result-map-pane, .route-grid, .route-card, .journey-guide").evaluateAll((elements) => elements.map((element) => {
    const bounds = element.getBoundingClientRect();
    return { left: bounds.left, right: bounds.right, width: bounds.width };
  }));
  for (const bounds of resultBounds) {
    expect(bounds.left).toBeGreaterThanOrEqual(-0.5);
    expect(bounds.right).toBeLessThanOrEqual(320.5);
    expect(bounds.width).toBeLessThanOrEqual(320.5);
  }

  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");
  expect(serious).toEqual([]);
});

test("returning home keeps the current-location control above the bottom navigation without a focus border", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 664 });
  await page.goto("/");
  const initialLocateBox = await page.getByRole("button", { name: "현재 위치로 지도 이동" }).boundingBox();
  expect(initialLocateBox).not.toBeNull();
  await page.getByRole("link", { name: "길찾기", exact: true }).click();
  await page.getByRole("link", { name: "홈", exact: true }).click();

  const locateButton = page.getByRole("button", { name: "현재 위치로 지도 이동" });
  const bottomNavigation = page.getByRole("navigation", { name: "모바일 주요 메뉴" });
  await expect(locateButton).toBeVisible();
  const [locateBox, navigationBox] = await Promise.all([locateButton.boundingBox(), bottomNavigation.boundingBox()]);
  expect(locateBox).not.toBeNull();
  expect(navigationBox).not.toBeNull();
  expect(Math.abs(locateBox!.y - initialLocateBox!.y)).toBeLessThanOrEqual(1);
  const navigationGap = navigationBox!.y - (locateBox!.y + locateBox!.height);
  expect(navigationGap).toBeGreaterThanOrEqual(30);
  expect(navigationGap).toBeLessThanOrEqual(70);
  await page.setViewportSize({ width: 390, height: 720 });
  const [resizedLocateBox, resizedNavigationBox] = await Promise.all([locateButton.boundingBox(), bottomNavigation.boundingBox()]);
  expect(resizedLocateBox).not.toBeNull();
  expect(resizedNavigationBox).not.toBeNull();
  const resizedGap = resizedNavigationBox!.y - (resizedLocateBox!.y + resizedLocateBox!.height);
  expect(Math.abs(resizedGap - navigationGap)).toBeLessThanOrEqual(1);
  await expect(page.locator("#main-content")).toHaveCSS("outline-style", "none");
});

test("offline state is explicit and does not pretend API data is available", async ({ context, page }) => {
  await page.goto("/");
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
  const cachedPaths = await page.evaluate(async () => {
    const requests = await (await caches.open("82ta-shell-v5")).keys();
    return requests.map((request) => new URL(request.url).pathname);
  });
  expect(cachedPaths).toContain("/");
  expect(cachedPaths.some((path) => path.startsWith("/assets/") && path.endsWith(".js"))).toBe(true);
  await context.setOffline(true);
  const offlineAssetStatus = await page.evaluate(async (path) => (await fetch(path)).status, cachedPaths.find((path) => path.endsWith(".js")) ?? "");
  expect(offlineAssetStatus).toBe(200);
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await expect(page.getByText(/오프라인입니다/)).toBeVisible();
  await expect(page.getByText(/새 검색과 계정 데이터는 연결 후 사용할 수 있습니다/)).toBeVisible();
});
