import type { RouteCandidate, RouteLeg } from "../../shared/api/publicService";

const internalTransportText = /^(?:(?:origin|destination|start|end)(?:\b|$)|kakao(?:\s+maps?)?\s+transit(?:\b|$)|sanitized(?:\b|[-_])|fixture(?:\b|[-_])|provider(?:\b|[-_]))/i;

function normalizeCustomerText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value
    .normalize("NFKC")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (normalized.length === 0 || internalTransportText.test(normalized)) return null;
  return normalized;
}

export function customerTransportText(value: unknown): string | null {
  return normalizeCustomerText(value);
}

function transitText(leg: RouteLeg, key: "routeLabel" | "direction"): string | null {
  const transit: unknown = leg.transit;
  if (transit === null || typeof transit !== "object" || Array.isArray(transit)) return null;
  return normalizeCustomerText((transit as Record<string, unknown>)[key]);
}

interface PresentedLegSeed {
  leg: RouteLeg;
  fromName: string | null;
  toName: string | null;
  routeLabel: string | null;
  direction: string | null;
}

export interface PresentedLeg {
  key: string;
  legs: readonly RouteLeg[];
  primaryLeg: RouteLeg;
  mode: RouteLeg["mode"];
  fromName: string;
  toName: string;
  routeLabel: string | null;
  direction: string | null;
  stationConnector: boolean;
}

function representativeLeg(legs: readonly RouteLeg[]): RouteLeg {
  return legs.reduce((selected, candidate) => {
    if (candidate.distanceMeters !== selected.distanceMeters) {
      return candidate.distanceMeters > selected.distanceMeters ? candidate : selected;
    }
    return candidate.duration.p50Seconds > selected.duration.p50Seconds ? candidate : selected;
  });
}

function isStationConnector(seed: PresentedLegSeed & { fromName: string; toName: string }): boolean {
  return (seed.leg.mode === "WALK" || seed.leg.mode === "TRANSFER") && seed.fromName === seed.toName;
}

export function presentedRouteLegs(route: RouteCandidate): PresentedLeg[] {
  if (route.legs.length === 0) return [];

  const seeds: PresentedLegSeed[] = route.legs.map((leg) => ({
    leg,
    fromName: normalizeCustomerText(leg.from.name),
    toName: normalizeCustomerText(leg.to.name),
    routeLabel: transitText(leg, "routeLabel"),
    direction: transitText(leg, "direction"),
  }));

  const first = seeds[0];
  const last = seeds.at(-1);
  if (first !== undefined && first.fromName === null) first.fromName = "출발지";
  if (last !== undefined && last.toName === null) last.toName = "도착지";

  for (let index = 0; index < seeds.length - 1; index += 1) {
    const current = seeds[index];
    const next = seeds[index + 1];
    if (current === undefined || next === undefined) continue;
    if (current.toName === null && next.fromName !== null) current.toName = next.fromName;
    if (next.fromName === null && current.toName !== null) next.fromName = current.toName;
  }

  const resolved = seeds.map((seed, index) => {
    const previous = seeds[index - 1];
    const next = seeds[index + 1];
    return {
      ...seed,
      fromName: seed.fromName ?? previous?.toName ?? (index === 0 ? "출발지" : "환승 지점"),
      toName: seed.toName ?? next?.fromName ?? (index === seeds.length - 1 ? "도착지" : "환승 지점"),
    };
  });

  const presented: PresentedLeg[] = [];
  for (const seed of resolved) {
    const stationConnector = isStationConnector(seed);
    const previous = presented.at(-1);
    if (
      stationConnector
      && previous?.stationConnector === true
      && previous.mode === seed.leg.mode
      && previous.fromName === seed.fromName
      && previous.toName === seed.toName
    ) {
      const legs = [...previous.legs, seed.leg];
      presented[presented.length - 1] = {
        ...previous,
        legs,
        primaryLeg: representativeLeg(legs),
      };
      continue;
    }

    presented.push({
      key: seed.leg.legId,
      legs: [seed.leg],
      primaryLeg: seed.leg,
      mode: seed.leg.mode,
      fromName: seed.fromName,
      toName: seed.toName,
      routeLabel: seed.routeLabel,
      direction: seed.direction,
      stationConnector,
    });
  }

  return presented;
}
