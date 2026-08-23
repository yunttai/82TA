import { describe, expect, it } from "vitest";

import { decodeGeoJsonLine, decodeStandardPolyline, MAX_GEOMETRY_POINTS } from "./polyline";

describe("standard polyline decoder", () => {
  it("decodes a valid bounded standard polyline", () => {
    const result = decodeStandardPolyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@");
    expect(result).toEqual({
      ok: true,
      points: [
        { lat: 38.5, lon: -120.2 },
        { lat: 40.7, lon: -120.95 },
        { lat: 43.252, lon: -126.453 },
      ],
    });
  });

  it("rejects malformed or incomplete input", () => {
    expect(decodeStandardPolyline("?????")).toEqual({ ok: false, reason: "MALFORMED" });
    expect(decodeStandardPolyline({ encoded: "???" })).toEqual({ ok: false, reason: "MALFORMED" });
  });

  it("rejects oversized encoded input before decoding", () => {
    expect(decodeStandardPolyline("a".repeat(100_001))).toEqual({ ok: false, reason: "OVERSIZED" });
  });
});

describe("bounded GeoJSON LineString decoder", () => {
  it("accepts finite WGS84 LineString points", () => {
    expect(decodeGeoJsonLine({ type: "LineString", coordinates: [[127.1, 37.3], [127.2, 37.4]] })).toEqual({
      ok: true,
      points: [{ lon: 127.1, lat: 37.3 }, { lon: 127.2, lat: 37.4 }],
    });
  });

  it("rejects malformed shape, non-finite values and excessive nesting", () => {
    expect(decodeGeoJsonLine({ type: "Point", coordinates: [127.1, 37.3] })).toEqual({ ok: false, reason: "MALFORMED" });
    expect(decodeGeoJsonLine({ type: "LineString", coordinates: [[127.1, 37.3], [Number.NaN, 37.4]] })).toEqual({ ok: false, reason: "MALFORMED" });
    expect(decodeGeoJsonLine({ geometry: { geometry: { geometry: { geometry: { geometry: { type: "LineString", coordinates: [[127.1, 37.3], [127.2, 37.4]] } } } } } })).toEqual({ ok: false, reason: "MALFORMED" });
  });

  it("rejects oversized coordinate arrays before mapping them", () => {
    const coordinates = Array.from({ length: MAX_GEOMETRY_POINTS + 1 }, () => [127.1, 37.3]);
    expect(decodeGeoJsonLine({ type: "LineString", coordinates })).toEqual({ ok: false, reason: "OVERSIZED" });
  });
});
