import { useState } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlaceField } from "./PlaceField";

function Harness() {
  const [value, setValue] = useState("");
  return <PlaceField label="출발지" value={value} onLabelChange={setValue} onPlaceSelected={() => undefined} />;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PlaceField request ordering", () => {
  it("does not show a stale suggestion after the query becomes too short", async () => {
    vi.useFakeTimers();
    let resolveRequest: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { resolveRequest = resolve; })));
    render(<Harness />);

    const field = screen.getByRole("combobox", { name: "출발지" });
    fireEvent.change(field, { target: { value: "판교" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(resolveRequest).toBeDefined();

    fireEvent.change(field, { target: { value: "판" } });
    await act(async () => {
      resolveRequest?.(new Response(JSON.stringify({
        items: [{ displayName: "오래된 판교역", coordinate: { lon: 127.1, lat: 37.3 } }],
      }), { status: 200, headers: { "content-type": "application/json" } }));
      await Promise.resolve();
    });

    expect(screen.queryByRole("option", { name: /오래된 판교역/ })).not.toBeInTheDocument();
    expect(field).toHaveValue("판");
  });

  it("distinguishes a rate limit from an empty result", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", {
      status: 429,
      headers: { "content-type": "application/problem+json" },
    })));
    render(<Harness />);

    fireEvent.change(screen.getByRole("combobox", { name: "출발지" }), { target: { value: "판교" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
      await Promise.resolve();
    });

    expect(screen.getByText(/장소 검색 요청이 많습니다/)).toBeInTheDocument();
    expect(screen.queryByText(/검색 결과가 없습니다/)).not.toBeInTheDocument();
  });

  it("shows the human-readable address without exposing provider metadata", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      items: [{
        displayName: "센트럴파크",
        address: "인천 연수구 컨벤시아대로 160",
        coordinate: { lon: 126.637, lat: 37.392 },
        provider: "KAKAO_LOCAL",
        regionCode: null,
      }],
    }), { status: 200, headers: { "content-type": "application/json" } })));
    render(<Harness />);

    fireEvent.change(screen.getByRole("combobox", { name: "출발지" }), { target: { value: "센트럴" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
      await Promise.resolve();
    });

    expect(screen.getByText("인천 연수구 컨벤시아대로 160")).toBeInTheDocument();
    expect(screen.queryByText(/지역 정보 없음/)).not.toBeInTheDocument();
    expect(screen.queryByText(/KAKAO_LOCAL/)).not.toBeInTheDocument();
  });
});
