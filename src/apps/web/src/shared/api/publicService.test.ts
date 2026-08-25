import { afterEach, describe, expect, it, vi } from "vitest";

import bikeOptions from "../../../../../contracts/openapi/examples/public-bike-options-response.json";
import { getBikeOptions } from "./publicService";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getBikeOptions", () => {
  it("uses the generated Public endpoint with origin and destination coordinates", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(bikeOptions), {
      status: 200,
      headers: { "content-type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getBikeOptions(
      { lon: 127.0301, lat: 37.4984 },
      { lon: 126.9733, lat: 37.556 },
    );

    expect(result.data).toEqual(bikeOptions);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [input, init] = fetchMock.mock.calls[0] ?? [];
    if (input === undefined) throw new Error("Expected a Public API request");
    const request = input instanceof Request ? input : new Request(input, init);
    const url = new URL(request.url);
    expect(url.pathname).toBe("/api/v1/bike-options");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      originLon: "127.0301",
      originLat: "37.4984",
      destinationLon: "126.9733",
      destinationLat: "37.556",
    });
    expect(request.credentials).toBe("same-origin");
  });
});
