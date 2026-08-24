import { useRef, useState } from "react";

import type { SearchDraft } from "./SearchForm";
import { expectedFareCapToTaxiBudgetKrw } from "./fareBudget";
import {
  createIdempotencyKey,
  createRouteSearch,
  type PublicProblem,
  type PublicRouteSearchRequest,
  type PublicRouteSearchResponse,
} from "../../shared/api/publicService";
import { ensureSearchSession } from "../../shared/session/sessionMemory";

type ResponsePhase = PublicRouteSearchResponse["status"];

type RouteSearchState =
  | { phase: "IDLE"; errors: readonly string[] }
  | { phase: "VALIDATING"; errors: readonly string[] }
  | { phase: "SEARCHING"; errors: readonly string[] }
  | { phase: ResponsePhase; errors: readonly string[]; response: PublicRouteSearchResponse; problem: null; request: PublicRouteSearchRequest }
  | { phase: "NO_FEASIBLE_ROUTE" | "PROVIDER_UNAVAILABLE" | "FAILED"; errors: readonly string[]; response: null; problem: PublicProblem | null };

interface ValidDraft {
  originLongitude: number;
  originLatitude: number;
  destinationLongitude: number;
  destinationLatitude: number;
  taxiBudgetKrw: number;
  maxWalkSeconds: number;
  maxTransfers: number;
  maxTaxiLegs: number;
  departureTime: string;
  arrivalDeadline: string | null;
}

interface ValidationResult {
  errors: readonly string[];
  value: ValidDraft | null;
}

function numberInRange(value: string, minimum: number, maximum: number): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= minimum && parsed <= maximum ? parsed : null;
}

function integerInRange(value: string, minimum: number, maximum: number): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= minimum && parsed <= maximum ? parsed : null;
}

function kstDateTime(value: string): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (match === null) return new Date(Number.NaN);
  const parsed = new Date(`${value}:00+09:00`);
  if (Number.isNaN(parsed.getTime())) return parsed;
  const normalized = new Date(parsed.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 16);
  return normalized === value ? parsed : new Date(Number.NaN);
}

function validateDraft(draft: SearchDraft): ValidationResult {
  const errors: string[] = [];
  const originLongitude = numberInRange(draft.originLongitude, 124, 132);
  const originLatitude = numberInRange(draft.originLatitude, 33, 39.5);
  const destinationLongitude = numberInRange(draft.destinationLongitude, 124, 132);
  const destinationLatitude = numberInRange(draft.destinationLatitude, 33, 39.5);
  const expectedFareCapKrw = integerInRange(draft.taxiBudgetKrw, 0, 500_000);
  const taxiBudgetKrw = expectedFareCapKrw === null
    ? null
    : expectedFareCapToTaxiBudgetKrw(expectedFareCapKrw, draft.fareCapUnconstrained);
  const maxWalkMinutes = numberInRange(draft.maxWalkMinutes, 0, 120);
  const maxWalkSeconds = maxWalkMinutes === null ? null : maxWalkMinutes * 60;
  const maxTransfers = integerInRange(draft.maxTransfers, 0, 8);
  const maxTaxiLegs = integerInRange(draft.maxTaxiLegs, 0, 3);
  const departureDate = draft.departureTiming === "NOW" ? new Date() : kstDateTime(draft.departureTime);
  const arrivalDeadlineDate = draft.arrivalDeadline.trim().length === 0 ? null : kstDateTime(draft.arrivalDeadline);

  if (draft.originName.trim().length === 0) errors.push("출발지 이름을 입력해 주세요.");
  if (originLongitude === null || originLatitude === null) errors.push("출발 좌표가 지원 범위를 벗어났습니다.");
  if (draft.destinationName.trim().length === 0) errors.push("목적지 이름을 입력해 주세요.");
  if (destinationLongitude === null || destinationLatitude === null) errors.push("도착 좌표가 지원 범위를 벗어났습니다.");
  if (taxiBudgetKrw === null) errors.push("예상 요금 상한은 0원부터 500,000원까지 정수로 입력해 주세요.");
  if (maxWalkSeconds === null || !Number.isInteger(maxWalkSeconds)) errors.push("최대 도보 시간은 0분부터 120분까지 초 단위로 정확히 입력해 주세요.");
  if (maxTransfers === null) errors.push("최대 환승 횟수를 확인해 주세요.");
  if (maxTaxiLegs === null) errors.push("최대 택시 구간 수를 확인해 주세요.");
  if (draft.allowedModes.length === 0) errors.push("교통수단을 하나 이상 선택해 주세요.");
  if (Number.isNaN(departureDate.getTime())) errors.push("출발 시각을 확인해 주세요.");
  if (arrivalDeadlineDate !== null && Number.isNaN(arrivalDeadlineDate.getTime())) errors.push("도착 마감 시각을 확인해 주세요.");
  if (arrivalDeadlineDate !== null && !Number.isNaN(arrivalDeadlineDate.getTime()) && arrivalDeadlineDate.getTime() <= departureDate.getTime()) {
    errors.push("도착 마감 시각은 출발 시각보다 뒤여야 합니다.");
  }

  if (
    errors.length > 0
    || originLongitude === null
    || originLatitude === null
    || destinationLongitude === null
    || destinationLatitude === null
    || taxiBudgetKrw === null
    || maxWalkSeconds === null
    || !Number.isInteger(maxWalkSeconds)
    || maxTransfers === null
    || maxTaxiLegs === null
    || Number.isNaN(departureDate.getTime())
    || (arrivalDeadlineDate !== null && Number.isNaN(arrivalDeadlineDate.getTime()))
  ) {
    return { errors, value: null };
  }

  return {
    errors,
    value: {
      originLongitude,
      originLatitude,
      destinationLongitude,
      destinationLatitude,
      taxiBudgetKrw,
      maxWalkSeconds,
      maxTransfers,
      maxTaxiLegs,
      departureTime: departureDate.toISOString(),
      arrivalDeadline: arrivalDeadlineDate?.toISOString() ?? null,
    },
  };
}

function buildRequest(draft: SearchDraft, valid: ValidDraft): PublicRouteSearchRequest {
  return {
    origin: {
      displayName: draft.originName.trim(),
      coordinate: { lon: valid.originLongitude, lat: valid.originLatitude },
    },
    destination: {
      displayName: draft.destinationName.trim(),
      coordinate: { lon: valid.destinationLongitude, lat: valid.destinationLatitude },
    },
    departure: { type: draft.departureType, time: valid.departureTime },
    arrivalDeadline: valid.arrivalDeadline,
    taxiBudget: { currency: "KRW", maxAmount: valid.taxiBudgetKrw, strict: true },
    preferences: {
      maxWalkSeconds: valid.maxWalkSeconds,
      maxTransfers: valid.maxTransfers,
      maxTaxiLegs: valid.maxTaxiLegs,
      allowTaxiBridge: draft.allowTaxiBridge,
      avoidHighBusSeatRisk: draft.avoidHighBusSeatRisk,
      allowedModes: draft.allowedModes,
      optimization: draft.optimization,
      accessibility: { avoidStairs: draft.avoidStairs, wheelchair: draft.wheelchair },
    },
    requestedRecommendations: ["FASTEST", "STABLE", "EFFICIENT", "PUBLIC_TRANSIT_ONLY"],
    saveToHistory: draft.saveToHistory,
  };
}

function errorPhase(problem: PublicProblem | undefined, status: number): "NO_FEASIBLE_ROUTE" | "PROVIDER_UNAVAILABLE" | "FAILED" {
  if (problem?.code === "NO_ROUTE_FOUND") return "NO_FEASIBLE_ROUTE";
  if (problem?.code === "TRANSIT_PROVIDER_UNAVAILABLE" || status === 503) return "PROVIDER_UNAVAILABLE";
  return "FAILED";
}

export function useRouteSearch() {
  const [state, setState] = useState<RouteSearchState>({ phase: "IDLE", errors: [] });
  const requestSequence = useRef(0);
  const lastAttempt = useRef<{ request: PublicRouteSearchRequest; idempotencyKey: string } | null>(null);

  async function execute(request: PublicRouteSearchRequest, idempotencyKey: string) {
    const sequence = ++requestSequence.current;
    setState({ phase: "SEARCHING", errors: [] });

    try {
      const { data, error, response } = await createRouteSearch(request, idempotencyKey);
      if (sequence !== requestSequence.current) return;

      if (data !== undefined) {
        setState({ phase: data.status, errors: [], response: data, problem: null, request });
        return;
      }

      setState({
        phase: errorPhase(error, response.status),
        errors: [],
        response: null,
        problem: error ?? null,
      });
    } catch {
      if (sequence === requestSequence.current) {
        setState({ phase: "FAILED", errors: [], response: null, problem: null });
      }
    }
  }

  async function search(draft: SearchDraft) {
    setState({ phase: "VALIDATING", errors: [] });
    await Promise.resolve();

    const validation = validateDraft(draft);
    if (validation.value === null) {
      setState({ phase: "VALIDATING", errors: validation.errors });
      return;
    }

    const request = buildRequest(draft, validation.value);
    const idempotencyKey = createIdempotencyKey();
    lastAttempt.current = { request, idempotencyKey };
    setState({ phase: "SEARCHING", errors: [] });
    try {
      await ensureSearchSession();
      await execute(request, idempotencyKey);
    } catch {
      setState({ phase: "FAILED", errors: [], response: null, problem: null });
    }
  }

  async function retry() {
    if (lastAttempt.current === null) return;
    await execute(lastAttempt.current.request, lastAttempt.current.idempotencyKey);
  }

  function reset() {
    requestSequence.current += 1;
    lastAttempt.current = null;
    setState({ phase: "IDLE", errors: [] });
  }

  return { state, search, retry, reset };
}
