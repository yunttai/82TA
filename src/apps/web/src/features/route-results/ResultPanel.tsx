import { useEffect, useState, type FormEvent } from "react";

import { RouteMap } from "../route-map/RouteMap";
import { publicTransitFareReserveKrw } from "../route-search/fareBudget";
import {
  presentedRouteLegs,
  type PresentedLeg,
} from "./itineraryPresentation";
import type {
  PublicCapabilities,
  PublicProblem,
  PublicRouteSearchResponse,
  RouteCandidate,
  RouteLeg,
} from "../../shared/api/publicService";
import { submitRouteFeedback } from "../../shared/api/publicService";
import { currentGuestToken } from "../../shared/session/sessionMemory";

interface ResultPanelProps {
  phase: PublicRouteSearchResponse["status"];
  response: PublicRouteSearchResponse | null;
  problem: PublicProblem | null;
  initialRouteId?: string;
  initialLegId?: string;
  strictTaxiBudgetKrw?: number;
  onRetry?: () => void;
  onRestart?: () => void;
}

const warningMessages: Readonly<Record<string, string>> = {
  BUS_DATA_UNAVAILABLE: "버스 실시간 정보를 사용할 수 없습니다.",
  BUS_MAPPING_LOW_CONFIDENCE: "일부 버스의 좌석·대기 정보는 표시하지 않습니다.",
  ETA_MODEL_FALLBACK: "실시간 도착정보가 없어 예상 도착시간을 사용했습니다.",
  HISTORICAL_PROXY_USED: "실시간 정보 대신 과거 자료를 사용했습니다.",
  TAXI_FARE_MAY_VARY: "실제 택시 요금은 달라질 수 있습니다.",
  TAXI_DISPATCH_WAIT_ESTIMATED: "택시 배차 대기는 추정값입니다.",
  TRANSFER_MARGIN_LOW: "환승 여유가 짧습니다.",
  GEOMETRY_PARTIAL: "일부 구간의 지도 경로가 없습니다.",
  PROVIDER_PARTIAL_FAILURE: "일부 교통 정보가 빠진 결과입니다.",
  DATA_STALE: "일부 정보가 오래되었습니다.",
  BUDGET_NEAR_LIMIT: "예상 요금이 설정한 상한에 가깝습니다.",
  BOARDABILITY_IS_PROXY: "탑승 가능성은 참고용이며 실제 탑승을 보장하지 않습니다.",
  FEATURE_OUT_OF_DISTRIBUTION: "평소와 다른 교통 상황에서는 예상이 달라질 수 있습니다.",
  FUTURE_TRANSIT_ESTIMATED: "미래 대중교통 정보는 과거 자료 기반 추정값입니다.",
};

const reasonMessages: Readonly<Record<string, string>> = {
  FASTER_THAN_PUBLIC_TRANSIT: "대중교통 기준보다 빠른 경로",
  BEST_MARGINAL_TIME_SAVING: "추가 비용 대비 시간 절감이 큰 경로",
  LOW_TRANSFER_RISK: "환승 여유가 비교적 큰 경로",
  UPSTREAM_STOP_HIGHER_BOARDABILITY: "상류 정류장 이동으로 대기 위험을 낮춘 경로",
  HIGH_BUS_SEAT_RISK_AVOIDED: "높은 좌석 부족 위험을 피한 경로",
  TAXI_BRIDGE_CONNECTS_FAST_LINES: "짧은 택시 이동으로 빠른 교통망을 연결한 경로",
  WITHIN_STRICT_TAXI_BUDGET: "예상 요금이 설정한 상한 이내인 경로",
  NO_MEANINGFUL_GAIN_FROM_MORE_BUDGET: "예산을 더 써도 시간 이득이 크지 않은 경로",
  LOWER_WALKING_TIME: "도보 시간이 짧은 경로",
  LOWER_P90_ARRIVAL_TIME: "보수적으로 보아도 도착이 빠른 경로",
};

const featureMessages: Readonly<Record<string, string>> = {
  currentTransit: "현재 대중교통",
  futureTransit: "미래 대중교통",
  currentTaxi: "현재 택시",
  futureTaxi: "미래 택시",
  multiDestinationTaxi: "택시 다중 목적지",
  busSeatRisk: "버스 좌석 위험",
  busEtaModel: "버스 도착 예측",
  taxiBridge: "택시 연결",
  realtimeRerouting: "실시간 재추천",
};

const coverageMessages = {
  LIVE: "실시간 정보 사용",
  PARTIAL: "일부 차량 정보만 사용",
  HISTORICAL: "과거 운행 정보 기반",
  UNSUPPORTED: "좌석 정보 미지원",
  UNKNOWN: "지원 여부 확인 불가",
} as const;

const modeMessages = {
  WALK: "도보",
  WAIT: "대기",
  TRANSFER: "환승 이동",
  TAXI: "택시",
  BUS: "버스",
  SUBWAY: "지하철",
  GTX: "GTX",
  TRAIN: "기차",
} as const;

const patternMessages: Readonly<Record<RouteCandidate["pattern"], string>> = {
  TRANSIT_ONLY: "대중교통 중심",
  TAXI_TRANSIT: "택시 후 대중교통",
  TRANSIT_TAXI: "대중교통 후 택시",
  TAXI_TRANSIT_TAXI: "택시·대중교통·택시",
  TAXI_ONLY: "택시만 이용",
  TRANSIT_TAXI_BRIDGE_TRANSIT: "대중교통 사이 택시 연결",
  UPSTREAM_STOP_TAXI_TRANSIT: "상류 정류장까지 택시 후 대중교통",
};

const resultStatusMessages = {
  COMPLETE: "추천 완료",
  PARTIAL: "일부 정보 제한",
  EXPIRED: "이전 검색 결과",
} as const;

const problemMessages: Readonly<Record<string, string>> = {
  INVALID_COORDINATE: "선택한 위치를 확인해 주세요.",
  UNSUPPORTED_TIME: "선택한 시각은 지원하지 않습니다.",
  ARRIVE_BY_UNSUPPORTED: "도착 시각 기준 검색은 아직 지원하지 않습니다.",
  CONSTRAINT_OUT_OF_RANGE: "이동 조건의 허용 범위를 확인해 주세요.",
  AUTH_REQUIRED: "로그인이 필요한 기능입니다.",
  SESSION_EXPIRED: "세션이 만료되었습니다.",
  CONSENT_REQUIRED: "이 기능을 사용하려면 관련 동의가 필요합니다.",
  UNSUPPORTED_REGION: "현재 지원 지역 밖입니다.",
  RATE_LIMITED: "요청이 많아 잠시 후 다시 시도해 주세요.",
  PROVIDER_BAD_RESPONSE: "교통 정보를 처리하지 못했습니다.",
  TRANSIT_PROVIDER_UNAVAILABLE: "대중교통 정보를 불러올 수 없습니다.",
  MODEL_NOT_READY: "일부 예측 기능을 사용할 수 없습니다.",
  ROUTING_DEADLINE_EXCEEDED: "검색 시간이 길어져 완료하지 못했습니다.",
};

type RecommendationKey = keyof PublicRouteSearchResponse["recommendations"];

const recommendationLabels: ReadonlyArray<readonly [RecommendationKey, string]> = [
  ["fastest", "가장 빠른 경로"],
  ["stable", "가장 안정적인 경로"],
  ["efficient", "비용 효율 경로"],
  ["publicTransitOnly", "대중교통만 이용"],
];

interface RecommendationCardItem {
  key: string;
  labels: readonly string[];
  route: RouteCandidate | null | undefined;
}

function recommendationCards(
  recommendations: PublicRouteSearchResponse["recommendations"],
): readonly RecommendationCardItem[] {
  const cards: RecommendationCardItem[] = [];
  const routeIndexes = new Map<string, number>();

  recommendationLabels.forEach(([key, label]) => {
    const route = recommendations[key];
    if (route == null) {
      cards.push({ key: `slot:${key}`, labels: [label], route });
      return;
    }

    const existingIndex = routeIndexes.get(route.routeId);
    if (existingIndex === undefined) {
      routeIndexes.set(route.routeId, cards.length);
      cards.push({ key: `route:${route.routeId}`, labels: [label], route });
      return;
    }

    const existing = cards[existingIndex];
    if (existing !== undefined) {
      cards[existingIndex] = { ...existing, labels: [...existing.labels, label] };
    }
  });

  return cards;
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder === 0 ? `${minutes}분` : `${minutes}분 ${remainder}초`;
}

function formatLegMinutes(seconds: number): string {
  if (seconds <= 0) return "0분";
  return `${Math.ceil(seconds / 60)}분`;
}

function formatWaitMinutes(seconds: number): string {
  if (seconds <= 0) return "곧 도착";
  return formatLegMinutes(seconds);
}

function routeLegLabel(leg: RouteLeg, taxiIncludesWait = false, routeLabel: string | null = null): string {
  if (leg.mode === "TAXI") return taxiIncludesWait ? "택시 (호출+주행)" : "택시";
  if (routeLabel === null) return modeMessages[leg.mode];
  if (leg.mode === "BUS") {
    return `버스 ${routeLabel.endsWith("번") ? routeLabel : `${routeLabel}번`}`;
  }
  if (leg.mode === "SUBWAY") return `지하철 ${routeLabel}`;
  if (leg.mode === "GTX") return `GTX ${routeLabel}`;
  if (leg.mode === "TRAIN") return `기차 ${routeLabel}`;
  return modeMessages[leg.mode];
}

const waitSeparatedModes = new Set<RouteLeg["mode"]>(["TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"]);

function waitLegLabel(mode: RouteLeg["mode"]): string {
  if (mode === "TAXI") return "택시 예상 대기";
  if (mode === "BUS") return "버스 대기";
  if (mode === "SUBWAY") return "지하철 대기";
  if (mode === "GTX") return "GTX 대기";
  if (mode === "TRAIN") return "기차 대기";
  return "대기";
}

interface RouteLegSummaryItem {
  key: string;
  mode: RouteLeg["mode"];
  label: string;
  p50Seconds: number;
  p90Seconds: number;
  durationText?: string;
  title: string;
  screenReaderText: string;
}

function routeLegSummaryItems(route: RouteCandidate): RouteLegSummaryItem[] {
  return presentedRouteLegs(route).flatMap((presented) => {
    const leg = presented.primaryLeg;
    const wait = leg.waitDuration;
    const travel = leg.travelDuration;
    if (waitSeparatedModes.has(leg.mode) && wait !== undefined && travel !== undefined) {
      const waitLabel = waitLegLabel(leg.mode);
      return [
        {
          key: `${leg.legId}:wait`,
          mode: "WAIT" as const,
          label: waitLabel,
          p50Seconds: wait.p50Seconds,
          p90Seconds: wait.p90Seconds,
          durationText: formatWaitMinutes(wait.p50Seconds),
          title: `${waitLabel} ${formatWaitMinutes(wait.p50Seconds)} · 길어지면 ${formatWaitMinutes(wait.p90Seconds)}`,
          screenReaderText: `${waitLabel}, 예상 ${formatWaitMinutes(wait.p50Seconds)}, 여유 기준 ${formatWaitMinutes(wait.p90Seconds)}`,
        },
        {
          key: leg.legId,
          mode: leg.mode,
          label: routeLegLabel(leg, false, presented.routeLabel),
          p50Seconds: travel.p50Seconds,
          p90Seconds: travel.p90Seconds,
          title: `${presented.fromName} → ${presented.toName} · 약 ${formatLegMinutes(travel.p50Seconds)} · 지연 시 ${formatLegMinutes(travel.p90Seconds)}`,
          screenReaderText: `${presented.fromName}에서 ${presented.toName}까지`,
        },
      ];
    }
    return [{
      key: leg.legId,
      mode: leg.mode,
      label: presented.stationConnector
        ? (leg.mode === "WALK" ? "환승 도보" : "환승 이동")
        : routeLegLabel(leg, leg.mode === "TAXI", presented.routeLabel),
      p50Seconds: leg.duration.p50Seconds,
      p90Seconds: leg.duration.p90Seconds,
      title: `${presented.fromName} → ${presented.toName} · 약 ${formatLegMinutes(leg.duration.p50Seconds)} · 지연 시 ${formatLegMinutes(leg.duration.p90Seconds)}`,
      screenReaderText: `${presented.fromName}에서 ${presented.toName}까지`,
    }];
  });
}

function formatMoney(amount: number): string {
  return `${new Intl.NumberFormat("ko-KR").format(amount)}원`;
}

function formatProbability(value: number): string {
  return new Intl.NumberFormat("ko-KR", { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function formatArrival(value: string | null | undefined): string {
  if (value == null) return "정보 없음";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "정보 확인 필요" : date.toLocaleString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function isRouteUsable(route: RouteCandidate, strictTaxiBudgetKrw?: number): boolean {
  if (route.totalDuration.p50Seconds < 0 || route.totalDuration.p90Seconds < route.totalDuration.p50Seconds) return false;
  if (route.taxiCost.lower < 0 || route.taxiCost.expected < route.taxiCost.lower || route.taxiCost.upper < route.taxiCost.expected) return false;
  if (strictTaxiBudgetKrw !== undefined && route.taxiCost.upper > strictTaxiBudgetKrw) return false;
  if (route.legs.some((leg) => {
    if (leg.duration.p50Seconds < 0 || leg.duration.p90Seconds < leg.duration.p50Seconds || leg.distanceMeters < 0) return true;
    const components = [leg.waitDuration, leg.travelDuration].filter((item) => item !== undefined);
    if (components.some((item) => item.p50Seconds < 0 || item.p90Seconds < item.p50Seconds)) return true;
    return components.length === 2
      && components.reduce((total, item) => total + item.p50Seconds, 0) > leg.duration.p50Seconds;
  })) return false;
  if (new Set(route.legs.map((leg) => leg.legId)).size !== route.legs.length) return false;
  return route.legs.every((leg, index) => {
    const previous = route.legs[index - 1];
    return previous === undefined || leg.sequence === previous.sequence + 1;
  });
}

function warningMessage(code: string): string {
  return warningMessages[code] ?? "일부 정보를 확인할 수 없습니다.";
}

function ReasonList({ codes }: { codes: readonly string[] }) {
  if (codes.length === 0) return null;
  return (
    <ul className="reason-list" aria-label="추천 이유">
      {codes.map((code) => <li key={code}>{reasonMessages[code] ?? "추가 추천 근거가 있습니다."}</li>)}
    </ul>
  );
}

function WarningList({ codes }: { codes: readonly string[] }) {
  if (codes.length === 0) return null;
  return (
    <ul className="warning-list" aria-label="주의할 정보">
      {codes.map((code) => <li key={code}>{warningMessage(code)}</li>)}
    </ul>
  );
}

function DegradedProvenanceList({ items }: { items: NonNullable<RouteCandidate["provenance"]> }) {
  const degradedItems = items.filter((item) => item.fallbackLevel > 0 || item.confidence.grade === "LOW");
  if (degradedItems.length === 0) return null;
  return (
    <ul className="provenance-list" aria-label="정보 정확도 안내">
      {degradedItems.map((item, index) => (
        <li key={`${item.origin}-${item.receivedAt}-${index}`}>
          <span>{item.fallbackLevel > 0 ? "일부 정보는 대체 자료를 사용했습니다." : "일부 정보의 정확도가 낮을 수 있습니다."}</span>
          {item.ageSeconds != null && <span>{formatDuration(item.ageSeconds)} 전에 받은 정보</span>}
        </li>
      ))}
    </ul>
  );
}

function formatDistance(meters: number): string {
  if (meters < 1_000) return `${meters}m`;
  return `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(meters / 1_000)}km`;
}

function rideAction(presented: PresentedLeg): string {
  const leg = presented.primaryLeg;
  if (presented.stationConnector) return `${presented.fromName}에서 환승 통로로 이동`;
  if (leg.mode === "WALK") return `${presented.toName}까지 걸어서 이동`;
  if (leg.mode === "TRANSFER") return `${presented.toName}으로 환승 이동`;
  if (leg.mode === "WAIT") return `${presented.fromName}에서 대기`;
  if (leg.mode === "TAXI") return `${presented.fromName}에서 택시 탑승`;
  return `${presented.fromName}에서 ${routeLegLabel(leg, false, presented.routeLabel)} 승차`;
}

function alightAction(presented: PresentedLeg): string | null {
  const mode = presented.primaryLeg.mode;
  if (mode === "WALK" || mode === "TRANSFER" || mode === "WAIT") return null;
  return `${presented.toName}에서 하차`;
}

function JourneyTimeline({
  route,
  selectedLegId,
  onSelectLeg,
}: {
  route: RouteCandidate;
  selectedLegId?: string;
  onSelectLeg: (legId: string) => void;
}) {
  const presentedLegs = presentedRouteLegs(route);
  const first = presentedLegs[0];
  const last = presentedLegs.at(-1);
  if (first === undefined || last === undefined) return null;

  return (
    <section className="journey-guide" aria-label="경로 상세">
      <div className="journey-guide-heading">
        <h4>경로 상세</h4>
        <strong>{presentedLegs.length}단계</strong>
      </div>
      <div className="journey-endpoint journey-origin">
        <span aria-hidden="true" />
        <div><small>출발</small><strong>{first.fromName}</strong></div>
      </div>
      <ol className="journey-timeline">
        {presentedLegs.map((presented, index) => {
          const leg = presented.primaryLeg;
          const selected = presented.legs.some((item) => item.legId === selectedLegId);
          const alight = alightAction(presented);
          return (
            <li
              className={selected ? "selected-leg" : undefined}
              aria-current={selected ? "step" : undefined}
              data-mode={leg.mode}
              key={presented.key}
            >
              <div className="journey-mode" aria-hidden="true">{modeMessages[leg.mode].slice(0, 1)}</div>
              <button
                className="journey-step-body"
                type="button"
                aria-pressed={selected}
                onClick={() => onSelectLeg(leg.legId)}
              >
                <span className="journey-step-number">{index + 1} · {modeMessages[leg.mode]}</span>
                <strong className="journey-action">{rideAction(presented)}</strong>
                {presented.direction !== null && <span className="journey-direction">{presented.direction}</span>}
                <div className="journey-step-metrics" aria-label={`${modeMessages[leg.mode]} 구간 정보`}>
                  <span>약 {formatLegMinutes(leg.duration.p50Seconds)}</span>
                  {leg.distanceMeters > 0 && <span>{formatDistance(leg.distanceMeters)}</span>}
                  {leg.waitDuration !== undefined && leg.waitDuration.p50Seconds > 0 && (
                    <span>대기 약 {formatLegMinutes(leg.waitDuration.p50Seconds)}</span>
                  )}
                  {leg.fare.expected > 0 && <span>예상 {formatMoney(leg.fare.expected)}</span>}
                </div>
                {alight !== null && <span className="journey-alight">{alight}</span>}
              </button>
            </li>
          );
        })}
      </ol>
      <div className="journey-endpoint journey-destination">
        <span aria-hidden="true" />
        <div><small>도착</small><strong>{last.toName}</strong></div>
      </div>
    </section>
  );
}

function BusIntelligence({ route, searchId }: { route: RouteCandidate; searchId: string }) {
  const busLegs = route.legs.filter((leg) => leg.busIntelligence != null);
  if (busLegs.length === 0) return null;
  const presentedLegs = presentedRouteLegs(route);

  return (
    <details className="bus-panel">
      <summary>버스 탑승 정보</summary>
      {busLegs.map((leg) => {
        const intelligence = leg.busIntelligence;
        if (intelligence == null) return null;
        const presented = presentedLegs.find((item) => item.legs.some((candidate) => candidate.legId === leg.legId));
        const mappingGrade = intelligence.mapping?.grade ?? "UNKNOWN";
        const safeToPresent = mappingGrade === "HIGH"
          && intelligence.p90WaitSeconds >= intelligence.expectedWaitSeconds;
        return (
          <div className="bus-leg" key={leg.legId}>
            <p><strong>{presented?.fromName ?? "승차 지점"} → {presented?.toName ?? "하차 지점"}</strong></p>
            {!safeToPresent ? (
              <p className="degraded-notice">좌석·대기 정보를 정확히 확인하기 어려워 기본 경로만 표시합니다.</p>
            ) : (
              <>
                <dl className="metric-grid compact">
                  <div><dt>현재 정보</dt><dd>{coverageMessages[intelligence.coverage]}</dd></div>
                  <div><dt>정류장 도착</dt><dd>{formatArrival(intelligence.userArrivalTime)}</dd></div>
                  <div><dt>예상 대기</dt><dd>{formatDuration(intelligence.expectedWaitSeconds)}</dd></div>
                  <div><dt>길어질 때</dt><dd>{formatDuration(intelligence.p90WaitSeconds)}</dd></div>
                </dl>
                <ul className="vehicle-list">
                  {intelligence.candidateVehicles.map((vehicle, index) => (
                    <li key={vehicle.vehicleRef}>
                      <span>다음 버스 {index + 1}</span>
                      <span>
                        약 {formatDuration(vehicle.eta.p50Seconds)} 뒤 도착 · 늦으면 {formatDuration(vehicle.eta.p90Seconds)}
                      </span>
                      <span>현재 확인된 좌석 {vehicle.remainSeatObserved == null ? "정보 없음" : `${vehicle.remainSeatObserved}석`}</span>
                      <span>
                        좌석 부족 가능성 {vehicle.seatRiskAtBoarding == null
                          ? "정보 없음"
                          : formatProbability(vehicle.seatRiskAtBoarding.noSeatProbability)}
                      </span>
                      <span>
                        여유 좌석 2석 이하 가능성 {vehicle.seatRiskAtBoarding == null
                          ? "정보 없음"
                          : formatProbability(vehicle.seatRiskAtBoarding.lowSeat2Probability)}
                      </span>
                      <span>
                        여유 좌석 5석 이하 가능성 {vehicle.seatRiskAtBoarding?.lowSeat5Probability == null
                          ? "정보 없음"
                          : formatProbability(vehicle.seatRiskAtBoarding.lowSeat5Probability)}
                      </span>
                      <span>
                        탑승 가능성 참고 {vehicle.boardabilityProxy == null
                          ? "정보 없음"
                          : formatProbability(vehicle.boardabilityProxy)}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="disclosure">표시된 시간과 좌석 정보는 예상값이며 실제 탑승을 보장하지 않습니다.</p>
              </>
            )}
            <WarningList codes={intelligence.warnings} />
            <a className="detail-link" href={`/searches/${encodeURIComponent(searchId)}/routes/${encodeURIComponent(route.routeId)}/bus/${encodeURIComponent(leg.legId)}`}>버스 구간 자세히 보기</a>
          </div>
        );
      })}
    </details>
  );
}

function RouteCard({
  labels,
  route,
  selected,
  selectedLegId,
  searchId,
  onSelect,
  onSelectLeg,
  strictTaxiBudgetKrw,
}: {
  labels: readonly string[];
  route: RouteCandidate | null | undefined;
  selected: boolean;
  selectedLegId?: string;
  searchId: string;
  onSelect: (route: RouteCandidate) => void;
  onSelectLeg: (legId: string) => void;
  strictTaxiBudgetKrw?: number;
}) {
  if (route == null) {
    return (
      <article className="route-card route-card-empty">
        <div className="card-kicker-list" aria-label="추천 유형">
          {labels.map((label) => <span className="card-kicker" key={label}>{label}</span>)}
        </div>
        <h3>추천 경로 없음</h3>
        <p>이 조건에서는 해당 추천 경로를 찾지 못했어요.</p>
      </article>
    );
  }

  if (!isRouteUsable(route, strictTaxiBudgetKrw)) {
    return (
      <article className="route-card route-card-empty" role="status">
        <div className="card-kicker-list" aria-label="추천 유형">
          {labels.map((label) => <span className="card-kicker" key={label}>{label}</span>)}
        </div>
        <h3>경로 정보를 검증할 수 없습니다</h3>
        <p>시간·비용 또는 이동 순서에 문제가 있어 이 경로를 표시하지 않았습니다. 다시 검색해 주세요.</p>
      </article>
    );
  }

  const summaryItems = routeLegSummaryItems(route);

  return (
    <article className={`route-card${selected ? " route-card-selected" : ""}`}>
      <div className="card-heading">
        <div>
          <div className="card-kicker-list" aria-label="추천 유형">
            {labels.map((label) => <span className="card-kicker" key={label}>{label}</span>)}
          </div>
          <h3>{formatDuration(route.totalDuration.p50Seconds)}</h3>
        </div>
      </div>
      <p className="route-pattern">{patternMessages[route.pattern]}</p>
      <ol className="route-leg-summary" aria-label="이동 구간 요약">
        {summaryItems.map((item) => (
          <li data-mode={item.mode} title={item.title} key={item.key}>
            <span className="route-leg-summary-label">{item.label}</span>
            <strong>{item.durationText ?? formatLegMinutes(item.p50Seconds)}</strong>
            <span className="sr-only">{item.screenReaderText}</span>
          </li>
        ))}
      </ol>
      {route.taxiLegCount > 0 && (
        <p className="taxi-duration-note">택시 예상 대기와 해당 시각의 도로 주행시간을 분리해 표시합니다.</p>
      )}
      <dl className="metric-grid metric-grid-primary">
        <div><dt>지연 고려</dt><dd>{formatDuration(route.totalDuration.p90Seconds)}</dd></div>
        <div><dt>택시비 최대 예상</dt><dd>{formatMoney(route.taxiCost.upper)}</dd></div>
        <div><dt>전체 예상 요금</dt><dd>{formatMoney(route.taxiCost.upper + publicTransitFareReserveKrw)}</dd></div>
        <div><dt>환승</dt><dd>{route.transferCount}회</dd></div>
      </dl>
      <button className="map-select-button" type="button" aria-pressed={selected} onClick={() => onSelect(route)}>
        {selected ? "선택한 경로" : "이 경로 지도·상세 보기"}
      </button>
      {selected && (
        <JourneyTimeline
          route={route}
          {...(selectedLegId === undefined ? {} : { selectedLegId })}
          onSelectLeg={onSelectLeg}
        />
      )}
      <ReasonList codes={route.reasonCodes} />
      <WarningList codes={route.warningCodes} />
      <details className="route-more">
        <summary>시간·요금 자세히</summary>
        <dl className="metric-grid">
          <div><dt>택시비 예상</dt><dd>{formatMoney(route.taxiCost.expected)}</dd></div>
          <div><dt>택시비 범위</dt><dd>{formatMoney(route.taxiCost.lower)}~{formatMoney(route.taxiCost.upper)}</dd></div>
          <div><dt>도보</dt><dd>{formatDuration(route.walkSeconds)}</dd></div>
          <div><dt>택시 구간</dt><dd>{route.taxiLegCount}개</dd></div>
          <div><dt>예상 도착</dt><dd>{formatArrival(route.arrivalAt?.p50)}</dd></div>
          <div><dt>지연 시 도착 예상</dt><dd>{formatArrival(route.arrivalAt?.p90)}</dd></div>
        </dl>
        <DegradedProvenanceList items={route.provenance ?? []} />
      </details>
      <BusIntelligence route={route} searchId={searchId} />
      <a className="detail-link" href={`/searches/${encodeURIComponent(searchId)}/routes/${encodeURIComponent(route.routeId)}`}>이 경로만 보기</a>
    </article>
  );
}

function FeedbackForm({ searchId, routeId, disabled = false }: { searchId: string; routeId: string | null; disabled?: boolean }) {
  const [status, setStatus] = useState<"IDLE" | "SENDING" | "DONE" | "FAILED">("IDLE");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (routeId === null) return;
    const data = new FormData(event.currentTarget);
    const rawRating = data.get("rating");
    const rating = typeof rawRating === "string" ? Number(rawRating) : null;
    const rawComment = data.get("comment");
    setStatus("SENDING");
    try {
      const { response } = await submitRouteFeedback(searchId, {
        selectedRouteId: routeId,
        rating: rating !== null && Number.isInteger(rating) && rating >= 1 && rating <= 5 ? rating : null,
        comment: typeof rawComment === "string" && rawComment.trim().length > 0 ? rawComment.trim() : null,
      }, currentGuestToken());
      setStatus(response.ok ? "DONE" : "FAILED");
    } catch {
      setStatus("FAILED");
    }
  }

  return (
    <details className="feedback-panel">
      <summary>이 추천에 의견 보내기</summary>
      {disabled ? <p>이전 검색 결과에는 의견을 남길 수 없습니다. 최신 경로를 다시 검색해 주세요.</p> : routeId === null ? <p>먼저 추천 경로를 선택해 주세요.</p> : (
        <form onSubmit={(event) => void submit(event)}>
          <label className="field">
            <span>만족도</span>
            <select name="rating" defaultValue="">
              <option value="">선택 안 함</option>
              {[5, 4, 3, 2, 1].map((rating) => <option key={rating} value={rating}>{rating}점</option>)}
            </select>
          </label>
          <label className="field">
            <span>의견(선택)</span>
            <textarea name="comment" maxLength={1000} />
          </label>
          <button className="secondary-button" type="submit" disabled={status === "SENDING" || status === "DONE"}>
            {status === "SENDING" ? "보내는 중…" : status === "DONE" ? "의견을 보냈습니다" : "의견 보내기"}
          </button>
          {status === "FAILED" && <p role="alert">의견을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.</p>}
        </form>
      )}
    </details>
  );
}

function SupportPanel({ support }: { support: PublicCapabilities }) {
  return (
    <details className="support-panel">
      <summary>현재 지원 범위</summary>
      <p>버스 정보 범위: <strong>{coverageMessages[support.busIntelligenceCoverage ?? "UNKNOWN"]}</strong></p>
      <ul className="feature-list">
        {Object.entries(support.features).map(([feature, supported]) => (
          <li key={feature}>
            <span>{featureMessages[feature] ?? "새 지원 항목"}</span>
            <strong>{supported === true ? "지원" : supported === false ? "미지원" : "알 수 없음"}</strong>
          </li>
        ))}
      </ul>
      {support.degraded.length > 0 && (
        <p className="degraded-copy">현재 {support.degraded.length}개 기능의 정보가 제한되어 있습니다. 각 경로의 안내를 확인해 주세요.</p>
      )}
    </details>
  );
}

function EmptyState({ phase, problem, onRetry, onRestart }: { phase: ResultPanelProps["phase"]; problem: PublicProblem | null; onRetry?: () => void; onRestart?: () => void }) {
  const content = phase === "NO_FEASIBLE_ROUTE"
    ? ["조건에 맞는 경로가 없습니다", "출발지·목적지와 출발 시간을 확인하거나 예상 요금 상한을 조정해 보세요."]
    : phase === "PROVIDER_UNAVAILABLE"
      ? ["교통 정보를 불러올 수 없습니다", "잠시 후 다시 검색해 주세요. 입력한 위치는 브라우저에 저장하지 않습니다."]
      : phase === "EXPIRED"
        ? ["이 결과는 만료되었습니다", "교통 정보가 달라졌을 수 있으니 같은 조건으로 다시 검색해 주세요."]
        : ["검색을 완료하지 못했습니다", problem === null ? "입력을 확인한 뒤 다시 시도해 주세요." : problemMessages[problem.code] ?? (problem.retryable ? "잠시 후 다시 시도해 주세요." : "입력을 확인한 뒤 다시 시도해 주세요.")];

  return (
    <section className="empty-state" aria-live="polite">
      <span aria-hidden="true">↻</span>
      <h2>{content[0]}</h2>
      <p>{content[1]}</p>
      {onRetry !== undefined && phase !== "EXPIRED" && <button className="secondary-button" type="button" onClick={onRetry}>같은 요청으로 다시 확인</button>}
      {onRestart !== undefined && phase === "EXPIRED" && <button className="secondary-button" type="button" onClick={onRestart}>입력 조건 다시 확인</button>}
    </section>
  );
}

export function ResultPanel({ phase, response, problem, initialRouteId, initialLegId, strictTaxiBudgetKrw, onRetry, onRestart }: ResultPanelProps) {
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [selectedLegId, setSelectedLegId] = useState<string | undefined>(initialLegId);
  const cards = response === null ? [] : recommendationCards(response.recommendations);

  useEffect(() => {
    if (response === null) {
      setSelectedRouteId(null);
      return;
    }
    const routes = recommendationCards(response.recommendations)
      .map((card) => card.route)
      .filter((route): route is RouteCandidate => route != null);
    const requested = routes.find((route) => route.routeId === initialRouteId);
    const selectedRoute = requested ?? routes[0];
    setSelectedRouteId(selectedRoute?.routeId ?? null);
    setSelectedLegId(selectedRoute?.legs.some((leg) => leg.legId === initialLegId) === true ? initialLegId : undefined);
  }, [initialLegId, initialRouteId, response]);

  if (response === null || phase === "NO_FEASIBLE_ROUTE" || phase === "PROVIDER_UNAVAILABLE" || phase === "FAILED") {
    return <EmptyState phase={phase} problem={problem} {...(onRetry === undefined ? {} : { onRetry })} {...(onRestart === undefined ? {} : { onRestart })} />;
  }

  return (
    <section className="results" aria-labelledby="results-title" aria-live="polite">
      <div className="results-heading">
        <div>
          <p className="section-number">02 · 비교 결과</p>
          <h2 id="results-title">도착 선택지</h2>
        </div>
        <span className={`status-badge status-${phase.toLowerCase()}`}>{resultStatusMessages[phase]}</span>
      </div>

      {phase === "EXPIRED" && (
        <div className="stale-result-banner" role="status">
          <div>
            <strong>이전 검색 결과를 보고 있어요.</strong>
            <p>보던 경로는 그대로 유지됩니다. 이동 전 다시 검색하면 최신 교통 정보를 확인할 수 있어요.</p>
          </div>
          {onRestart !== undefined && <button type="button" onClick={onRestart}>검색 조건 확인</button>}
        </div>
      )}

      {phase === "PARTIAL" && (
        <div className="partial-banner" role="status">
          <strong>일부 정보 없이 계산한 결과입니다.</strong>
          <p>이동 경로는 확인할 수 있지만 아래 경고와 지원 범위를 함께 살펴보세요.</p>
        </div>
      )}

      <WarningList codes={response.warnings} />
      <div className="results-workspace">
        <div className="result-map-pane">
          <RouteMap
            route={cards
              .map((card) => card.route)
              .find((route) => route?.routeId === selectedRouteId) ?? null}
            {...(selectedLegId === undefined ? {} : { selectedLegId })}
          />
        </div>
        <div className="route-grid" aria-label="추천 경로 목록">
          {cards.map((card) => (
            <RouteCard
              key={card.key}
              labels={card.labels}
              route={card.route}
              selected={card.route?.routeId === selectedRouteId}
              {...(selectedLegId === undefined ? {} : { selectedLegId })}
              searchId={response.searchId}
              onSelect={(route) => {
                setSelectedRouteId(route.routeId);
                setSelectedLegId(undefined);
              }}
              onSelectLeg={setSelectedLegId}
              {...(strictTaxiBudgetKrw === undefined ? {} : { strictTaxiBudgetKrw })}
            />
          ))}
        </div>
      </div>
      {response.baseline != null && (
        <section className="baseline-panel" aria-label="대중교통 기준 경로">
          <strong>대중교통 기준</strong>
          <span>예상 소요 {formatDuration(response.baseline.totalDuration.p50Seconds)}</span>
          <span>지연 고려 {formatDuration(response.baseline.totalDuration.p90Seconds)}</span>
          <span>택시비 최대 예상 {formatMoney(response.baseline.taxiCost.upper)}</span>
        </section>
      )}
      {response.paretoFrontier !== undefined && response.paretoFrontier.length > 0 && (
        <div className="pareto-panel">
          <h3>예산과 도착시간 비교</h3>
          <div className="table-scroll" role="region" aria-label="예산과 도착시간 비교 표" tabIndex={0}>
            <table>
              <thead><tr><th>경로</th><th>택시비 최대 예상</th><th>예상 소요</th><th>지연 고려</th></tr></thead>
              <tbody>{response.paretoFrontier.map((item, index) => (
                <tr key={item.routeId}><td>비교 경로 {index + 1}</td><td>{formatMoney(item.taxiCostUpper)}</td><td>{formatDuration(item.p50Seconds)}</td><td>{formatDuration(item.p90Seconds)}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </div>
      )}
      <SupportPanel support={response.support} />
      <FeedbackForm searchId={response.searchId} routeId={selectedRouteId} disabled={phase === "EXPIRED"} />
    </section>
  );
}
