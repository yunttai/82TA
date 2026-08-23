import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import canonicalResponse from "../../../contracts/openapi/examples/public-route-search-response.json" with { type: "json" };

const guestToken = "guest_e2e_0123456789abcdef0123456789abcdef";

async function mockPublicApi(page: Page) {
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
    if (path === "/api/v1/guest-sessions" && request.method() === "POST") {
      await route.fulfill({ status: 201, json: { guestToken, expiresAt: "2099-08-24T07:40:00+09:00" } });
      return;
    }
    if (path === "/api/v1/session" && request.method() === "GET") {
      if (request.headers()["x-guest-token"] === guestToken) {
        await route.fulfill({ json: { subjectType: "GUEST", authenticated: false, expiresAt: "2099-08-24T07:40:00+09:00" } });
      } else {
        await route.fulfill({ status: 401, contentType: "application/problem+json", body: "{}" });
      }
      return;
    }
    if (path === "/api/v1/route-searches" && request.method() === "POST") {
      await route.fulfill({
        json: {
          ...canonicalResponse,
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

test("mobile route search stays within the Public Service boundary", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.goto("/");

  expect(await page.locator("body").innerText()).toContain("어디로 갈까요?");
  await expect(page.getByRole("navigation", { name: "모바일 주요 메뉴" })).toBeVisible();
  await expect(page.getByRole("link", { name: "길찾기" })).toHaveAttribute("aria-current", "page");
  await page.getByText("지도에서 직접 위치 선택").click();
  await expect(page.getByText("지도 선택을 사용할 수 없습니다.")).toBeVisible();
  await expect(page.getByText(/좌표를 직접 입력해 주세요/)).toBeVisible();
  await page.getByRole("button", { name: "내 예산으로 경로 찾기" }).click();
  await expect(page.getByText("일부 정보 없이 계산한 결과입니다.")).toBeVisible();
  await expect(page.getByText("추천 경로 없음")).toHaveCount(4);

  expect(requests.some((url) => new URL(url).pathname === "/api/v1/route-searches")).toBe(true);
  expect(requests.some((url) => /\/v1\/routes\/optimize/.test(new URL(url).pathname))).toBe(false);
});

test("320px layout has no horizontal page overflow and no serious accessibility violations", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/");
  const bottomNav = page.getByRole("navigation", { name: "모바일 주요 메뉴" });
  await expect(bottomNav).toHaveCSS("position", "fixed");
  await expect(page.getByRole("heading", { name: "어디로 갈까요?" })).toBeVisible();
  await expect(page.getByText("지도에서 직접 위치 선택")).toBeVisible();
  await expect(page.getByText("지도 선택을 사용할 수 없습니다.")).not.toBeVisible();
  const sizes = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, content: document.documentElement.scrollWidth }));
  expect(sizes.content).toBeLessThanOrEqual(sizes.viewport);

  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");
  expect(serious).toEqual([]);
});

test("offline state is explicit and does not pretend API data is available", async ({ context, page }) => {
  await page.goto("/");
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
  const cachedPaths = await page.evaluate(async () => {
    const requests = await (await caches.open("82ta-shell-v2")).keys();
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
