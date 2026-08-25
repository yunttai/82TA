import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSessionMemory } from "../shared/session/sessionMemory";
import { AccountPage } from "./ServicePages";

const registeredSession = {
  subjectType: "USER",
  authenticated: true,
  expiresAt: "2099-08-25T00:00:00+09:00",
  email: "new-user@example.com",
  nickname: "새사용자",
} as const;

function json(value: unknown, status = 200, contentType = "application/json"): Response {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": contentType } });
}

function problem(status: number, violations: { field?: string; message?: string }[] = []): Response {
  return json({
    type: "https://api.example.invalid/problems/test",
    title: "Safe account error",
    status,
    code: status === 429 ? "RATE_LIMITED" : "CONSTRAINT_OUT_OF_RANGE",
    detail: null,
    retryable: status === 429,
    correlationId: "safe-correlation",
    violations,
    safeContext: {},
  }, status, "application/problem+json");
}

function accountFetch(registrationResponse: Response) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const request = input instanceof Request ? input : new Request(input);
    const path = new URL(request.url).pathname;
    if (path === "/api/v1/session") return problem(401);
    if (path === "/api/v1/health") return json({ status: "ok" });
    if (path === "/api/v1/auth/register") return registrationResponse.clone();
    return problem(404);
  });
}

async function fillRegistration(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("tab", { name: "회원가입" }));
  await user.type(screen.getByRole("textbox", { name: /닉네임/ }), "새사용자");
  await user.type(screen.getByRole("textbox", { name: /이메일/ }), "new-user@example.com");
  await user.type(screen.getByLabelText(/비밀번호/), "correct-horse-battery-staple");
}

beforeEach(() => {
  clearSessionMemory();
  vi.stubEnv("VITE_PRIVACY_DOCUMENT_VERSION", "local-development");
  document.cookie = "csrftoken=account-csrf; Path=/; SameSite=Lax";
});

afterEach(() => {
  document.cookie = "csrftoken=; Max-Age=0; Path=/";
  clearSessionMemory();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("AccountPage registration", () => {
  it("submits the current consent bundle and renders the authenticated profile", async () => {
    const fetchMock = accountFetch(json(registeredSession, 201));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<AccountPage />);

    await fillRegistration(user);
    await user.click(screen.getByRole("checkbox", { name: /필수.*개인정보 처리/ }));
    await user.click(screen.getByRole("checkbox", { name: "검색 기록 저장" }));
    await user.click(screen.getByRole("button", { name: "계정 만들기" }));

    expect(await screen.findByText("로그인됨")).toBeInTheDocument();
    expect(screen.getByText("새사용자")).toBeInTheDocument();
    const registrationCall = fetchMock.mock.calls.find(([input]) => {
      const request = input instanceof Request ? input : new Request(input);
      return new URL(request.url).pathname === "/api/v1/auth/register";
    });
    if (registrationCall === undefined) throw new Error("Expected registration request");
    const request = registrationCall[0] instanceof Request ? registrationCall[0].clone() : new Request(registrationCall[0]);
    expect(request.headers.get("X-CSRFToken")).toBe("account-csrf");
    expect(await request.json()).toEqual({
      email: "new-user@example.com",
      password: "correct-horse-battery-staple",
      nickname: "새사용자",
      documentVersion: "local-development",
      requiredPrivacyAccepted: true,
      optionalConsents: {
        SEARCH_HISTORY: true,
        PRECISE_LOCATION: false,
        PRODUCT_ANALYTICS: false,
        ROUTING_FEEDBACK: false,
      },
    });
  });

  it("does not submit when required privacy acceptance is absent even if native validation is bypassed", async () => {
    const fetchMock = accountFetch(json(registeredSession, 201));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<AccountPage />);

    await fillRegistration(user);
    const submit = screen.getByRole("button", { name: "계정 만들기" });
    const form = submit.closest("form");
    if (form === null) throw new Error("Expected registration form");
    fireEvent.submit(form);

    expect(await screen.findByText("필수 개인정보 안내에 동의해야 계정을 만들 수 있습니다.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => new URL(input instanceof Request ? input.url : input.toString()).pathname === "/api/v1/auth/register")).toBe(false);
  });

  it.each([
    [problem(400, [{ field: "nickname", message: "invalid" }]), "입력 내용을 확인해 주세요. 닉네임은 2~20자, 비밀번호는 12자 이상이어야 합니다."],
    [problem(400, [{ field: "documentVersion", message: "stale" }]), "앱 버전이 서버와 맞지 않습니다. 새 버전을 불러온 뒤 다시 가입해 주세요."],
    [problem(403), "보안 확인이 만료되었습니다. 화면을 새로고침한 뒤 다시 시도해 주세요."],
    [problem(409), "이미 가입된 이메일입니다. 로그인해 주세요."],
    [problem(429), "가입 요청이 많습니다. 1분 뒤 다시 시도해 주세요."],
    [problem(500), "지금은 계정 요청을 처리할 수 없습니다. 잠시 후 다시 시도해 주세요."],
  ])("shows an actionable safe message for a failed registration", async (response, message) => {
    vi.stubGlobal("fetch", accountFetch(response));
    const user = userEvent.setup();
    render(<AccountPage />);

    await fillRegistration(user);
    await user.click(screen.getByRole("checkbox", { name: /필수.*개인정보 처리/ }));
    await user.click(screen.getByRole("button", { name: "계정 만들기" }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/safe-correlation|CONSTRAINT_OUT_OF_RANGE|RATE_LIMITED/);
    await waitFor(() => expect(screen.getByRole("textbox", { name: /이메일/ })).toHaveValue("new-user@example.com"));
  });
});
