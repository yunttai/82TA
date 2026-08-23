export interface CoordinatePair {
  lon: number;
  lat: number;
}

export type PolylineDecodeResult =
  | { ok: true; points: CoordinatePair[] }
  | { ok: false; reason: "MALFORMED" | "OVERSIZED" };

const MAX_ENCODED_LENGTH = 100_000;
export const MAX_GEOMETRY_POINTS = 10_000;
const MAX_GEOJSON_DEPTH = 4;

export function decodeGeoJsonLine(value: unknown, depth = 0): PolylineDecodeResult {
  if (depth > MAX_GEOJSON_DEPTH || typeof value !== "object" || value === null) return { ok: false, reason: "MALFORMED" };
  if (!("type" in value) || !("coordinates" in value)) {
    return "geometry" in value ? decodeGeoJsonLine(value.geometry, depth + 1) : { ok: false, reason: "MALFORMED" };
  }
  if (value.type !== "LineString" || !Array.isArray(value.coordinates)) return { ok: false, reason: "MALFORMED" };
  if (value.coordinates.length > MAX_GEOMETRY_POINTS) return { ok: false, reason: "OVERSIZED" };
  if (value.coordinates.length < 2) return { ok: false, reason: "MALFORMED" };

  const points: CoordinatePair[] = [];
  for (const coordinate of value.coordinates) {
    if (!Array.isArray(coordinate) || coordinate.length < 2) return { ok: false, reason: "MALFORMED" };
    const [lon, lat] = coordinate;
    if (typeof lon !== "number" || typeof lat !== "number" || !Number.isFinite(lon) || !Number.isFinite(lat)
      || lon < -180 || lon > 180 || lat < -90 || lat > 90) return { ok: false, reason: "MALFORMED" };
    points.push({ lon, lat });
  }
  return { ok: true, points };
}

export function decodeStandardPolyline(value: unknown): PolylineDecodeResult {
  if (typeof value !== "string" || value.length === 0) return { ok: false, reason: "MALFORMED" };
  if (value.length > MAX_ENCODED_LENGTH) return { ok: false, reason: "OVERSIZED" };
  const encoded = value;

  let index = 0;
  let latitude = 0;
  let longitude = 0;
  const points: CoordinatePair[] = [];

  function readDelta(): number | null {
    let result = 0;
    let shift = 0;
    while (index < encoded.length) {
      const byte = encoded.charCodeAt(index++) - 63;
      if (byte < 0 || byte > 63 || shift > 30) return null;
      result += (byte & 0x1f) * 2 ** shift;
      if (byte < 0x20) return result % 2 === 1 ? -(Math.floor(result / 2) + 1) : Math.floor(result / 2);
      shift += 5;
    }
    return null;
  }

  while (index < encoded.length) {
    if (points.length >= MAX_GEOMETRY_POINTS) return { ok: false, reason: "OVERSIZED" };
    const latitudeDelta = readDelta();
    const longitudeDelta = readDelta();
    if (latitudeDelta === null || longitudeDelta === null) return { ok: false, reason: "MALFORMED" };
    latitude += latitudeDelta;
    longitude += longitudeDelta;
    const point = { lat: latitude / 1e5, lon: longitude / 1e5 };
    if (!Number.isFinite(point.lat) || !Number.isFinite(point.lon)
      || point.lat < -90 || point.lat > 90 || point.lon < -180 || point.lon > 180) {
      return { ok: false, reason: "MALFORMED" };
    }
    points.push(point);
  }

  return points.length >= 2 ? { ok: true, points } : { ok: false, reason: "MALFORMED" };
}
