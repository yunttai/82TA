import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PreferencesPage } from "./ServicePages";

afterEach(() => {
  document.cookie = "csrftoken=; Max-Age=0; Path=/";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PreferencesPage contract-backed accessibility", () => {
  it("sends both typed accessibility flags with the server ETag", async () => {
    document.cookie = "csrftoken=preferences-csrf; Path=/; SameSite=Lax";
    const preferences = {
      defaultTaxiBudget: 10000,
      maxWalkSeconds: 900,
      maxTransfers: 3,
      maxTaxiLegs: 2,
      optimizationProfile: "BALANCED",
      accessibility: { avoidStairs: false, wheelchair: false },
      privacy: {},
      version: 3,
      updatedAt: "2026-08-23T00:00:00+09:00",
    } as const;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(input);
      if (request.url.endsWith("/api/v1/health")) {
        return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify(preferences), {
        status: 200,
        headers: { "content-type": "application/json", etag: '"3"' },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<PreferencesPage />);

    await user.click(await screen.findByRole("checkbox", { name: "계단이 있는 경로 피하기" }));
    await user.click(screen.getByRole("checkbox", { name: "휠체어 접근 가능한 경로 우선" }));
    await user.click(screen.getByRole("button", { name: "선호 저장" }));

    await waitFor(() => expect(screen.getByText("선호를 저장했습니다.")).toBeInTheDocument());
    const putCall = fetchMock.mock.calls.find(([input]) => {
      const request = input instanceof Request ? input : new Request(input);
      return request.method === "PUT";
    });
    if (putCall === undefined) throw new Error("Expected preference mutation");
    const request = putCall[0] instanceof Request ? putCall[0].clone() : new Request(putCall[0]);
    expect(request.headers.get("If-Match")).toBe('"3"');
    expect(await request.json()).toMatchObject({ accessibility: { avoidStairs: true, wheelchair: true } });
  });
});
