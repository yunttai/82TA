import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PrivacyPage } from "./ServicePages";

afterEach(() => {
  document.cookie = "csrftoken=; Max-Age=0; Path=/";
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PrivacyPage consent document version", () => {
  it("submits the exact server-aligned deployment version without a UI constant", async () => {
    const documentVersion = "privacy-ko-2026.08.23";
    vi.stubEnv("VITE_PRIVACY_DOCUMENT_VERSION", documentVersion);
    document.cookie = "csrftoken=privacy-csrf; Path=/; SameSite=Lax";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(input);
      if (request.url.endsWith("/api/v1/me/consents") && request.method === "GET") {
        return new Response(JSON.stringify({ items: [] }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (request.url.endsWith("/api/v1/health")) {
        return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({
        consentType: "SEARCH_HISTORY",
        documentVersion,
        accepted: true,
        recordedAt: "2026-08-23T00:00:00+09:00",
      }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<PrivacyPage />);

    const consentButtons = await screen.findAllByRole("button", { name: "동의" });
    const firstButton = consentButtons[0];
    if (firstButton === undefined) throw new Error("Expected consent action");
    await user.click(firstButton);

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => {
      const request = input instanceof Request ? input : new Request(input);
      return request.method === "PUT";
    })).toBe(true));
    const mutation = fetchMock.mock.calls.find(([input]) => {
      const request = input instanceof Request ? input : new Request(input);
      return request.method === "PUT";
    });
    if (mutation === undefined) throw new Error("Expected consent mutation");
    const request = mutation[0] instanceof Request ? mutation[0].clone() : new Request(mutation[0]);
    expect(await request.json()).toMatchObject({ documentVersion, accepted: true });
  });

  it("does not expose an expired export download URL", async () => {
    vi.stubEnv("VITE_PRIVACY_DOCUMENT_VERSION", "privacy-test");
    document.cookie = "csrftoken=privacy-csrf; Path=/; SameSite=Lax";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input instanceof Request ? input : new Request(input);
      if (request.url.endsWith("/api/v1/me/consents")) {
        return new Response(JSON.stringify({ items: [] }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (request.url.endsWith("/api/v1/health")) {
        return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (request.url.endsWith("/api/v1/me/data-exports") && request.method === "POST") {
        return new Response(JSON.stringify({
          jobId: "11111111-1111-4111-8111-111111111111",
          type: "EXPORT",
          status: "PENDING",
          requestedAt: "2026-08-23T00:00:00+09:00",
        }), { status: 202, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({
        jobId: "11111111-1111-4111-8111-111111111111",
        type: "EXPORT",
        status: "COMPLETE",
        requestedAt: "2026-08-23T00:00:00+09:00",
        completedAt: "2026-08-23T00:01:00+09:00",
        downloadUrl: "https://example.test/private-export.zip",
        downloadExpiresAt: "2026-08-23T00:02:00+09:00",
        failureCode: null,
      }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<PrivacyPage />);

    await user.click(await screen.findByRole("button", { name: "내 데이터 받기" }));
    await user.click(await screen.findByRole("button", { name: "상태 새로고침" }));

    expect(await screen.findByText(/다운로드 기간이 지났습니다/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "만료 전 다운로드" })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("private-export.zip");
  });
});
