import { useEffect, useState } from "react";

import {
  getBikeOptions,
  type BikeOptionsResponse,
  type BikeStationOption,
  type PlaceRef,
} from "../../shared/api/publicService";

interface BikeOptionsPanelProps {
  origin: PlaceRef["coordinate"];
  destination: PlaceRef["coordinate"];
}

type BikeOptionsState =
  | { phase: "LOADING" }
  | { phase: "SUCCESS"; data: BikeOptionsResponse; pickup: BikeStationOption; returnStation: BikeStationOption }
  | { phase: "EMPTY"; data: BikeOptionsResponse }
  | { phase: "ERROR" };

function formatDuration(seconds: number): string {
  return `약 ${Math.ceil(seconds / 60).toLocaleString("ko-KR")}분`;
}

function formatDistance(meters: number): string {
  if (meters < 1_000) return `${meters.toLocaleString("ko-KR")}m`;
  return `${(meters / 1_000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}km`;
}

function formatSnapshotMonth(value: string): string {
  const [year, month] = value.split("-");
  return `${year}년 ${Number(month)}월 기준`;
}

function officialSourceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "data.seoul.go.kr" ? url.href : null;
  } catch {
    return null;
  }
}

function resolveEstimate(data: BikeOptionsResponse): {
  pickup: BikeStationOption;
  returnStation: BikeStationOption;
} | null {
  const estimate = data.rideEstimate;
  if (estimate === null || estimate.pickupStationId === estimate.returnStationId) return null;

  const pickup = data.pickupStations.find((station) => station.stationId === estimate.pickupStationId);
  const returnStation = data.returnStations.find((station) => station.stationId === estimate.returnStationId);
  return pickup === undefined || returnStation === undefined ? null : { pickup, returnStation };
}

function StationGroup({
  heading,
  primary,
  alternatives,
  pointLabel,
}: {
  heading: string;
  primary: BikeStationOption;
  alternatives: readonly BikeStationOption[];
  pointLabel: "출발지" | "목적지";
}) {
  return (
    <section className="bike-station-group">
      <h3>{heading}</h3>
      <div className="bike-station-primary">
        <strong>{primary.name}</strong>
        <p>{primary.address ?? primary.district}</p>
        <span>{pointLabel}에서 {formatDistance(primary.distanceFromPointMeters)}</span>
      </div>
      {alternatives.length > 0 && (
        <div className="bike-station-alternatives">
          <p><strong>다른 후보</strong></p>
          <ul aria-label={`${heading} 다른 후보`}>
            {alternatives.map((station) => (
              <li key={station.stationId}>
                <span>{station.name}</span>
                <small>{station.address ?? station.district} · {pointLabel}에서 {formatDistance(station.distanceFromPointMeters)}</small>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function DataSource({ data, speedKph = 15 }: { data: BikeOptionsResponse; speedKph?: number }) {
  const sourceUrl = officialSourceUrl(data.dataSource.url);
  return (
    <div className="bike-disclosures">
      <p><strong>계산 기준</strong> 직선거리·시속 {speedKph}km 단순 예상</p>
      <p><strong>이용 전 확인</strong> 실시간 대여 가능 수량은 따릉이 앱에서 확인</p>
      <p>
        {formatSnapshotMonth(data.stationDataMonth)} ·{" "}
        {sourceUrl === null ? data.dataSource.name : (
          <a href={sourceUrl} target="_blank" rel="noreferrer" aria-label="서울시 데이터 출처 (새 창)">서울시 데이터 출처</a>
        )}
      </p>
    </div>
  );
}

export function BikeOptionsPanel({ origin, destination }: BikeOptionsPanelProps) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<BikeOptionsState>({ phase: "LOADING" });

  useEffect(() => {
    let active = true;
    setState({ phase: "LOADING" });

    void getBikeOptions(origin, destination).then(({ data, response }) => {
      if (!active) return;
      if (!response.ok || data === undefined) {
        setState({ phase: "ERROR" });
        return;
      }

      if (data.rideEstimate === null) {
        setState({ phase: "EMPTY", data });
        return;
      }

      const stations = resolveEstimate(data);
      setState(stations === null
        ? { phase: "ERROR" }
        : { phase: "SUCCESS", data, ...stations });
    }).catch(() => {
      if (active) setState({ phase: "ERROR" });
    });

    return () => {
      active = false;
    };
  }, [origin.lon, origin.lat, destination.lon, destination.lat, attempt]);

  const busy = state.phase === "LOADING";

  return (
    <section className="bike-options-panel" aria-labelledby="bike-options-title" aria-busy={busy}>
      <header className="bike-options-heading">
        <span className="bike-options-mark" aria-hidden="true">자전거</span>
        <div>
          <p className="eyebrow">경로 추천과 별도 옵션</p>
          <h2 id="bike-options-title">따릉이로 이동하기</h2>
        </div>
      </header>

      {state.phase === "LOADING" && (
        <div className="bike-options-state" role="status" aria-live="polite">
          <span className="bike-loading-mark" aria-hidden="true" />
          <div><strong>가까운 따릉이 대여소를 찾고 있어요</strong><p>기존 길찾기 결과는 그대로 확인할 수 있습니다.</p></div>
        </div>
      )}

      {state.phase === "ERROR" && (
        <div className="bike-options-state bike-options-error" role="status">
          <div><strong>따릉이 정보를 불러오지 못했어요</strong><p>길찾기 결과에는 영향이 없습니다. 잠시 후 다시 확인해 주세요.</p></div>
          <button type="button" onClick={() => setAttempt((value) => value + 1)}>따릉이 정보 다시 불러오기</button>
        </div>
      )}

      {state.phase === "EMPTY" && (
        <div className="bike-options-empty">
          <div role="status">
            <strong>가까운 대여소 조합을 찾지 못했어요</strong>
            <p>출발지 또는 목적지 반경 {formatDistance(state.data.searchRadiusMeters)} 안에 서로 다른 대여소가 없습니다.</p>
          </div>
          <DataSource data={state.data} />
        </div>
      )}

      {state.phase === "SUCCESS" && state.data.rideEstimate !== null && (
        <>
          <div
            className="bike-estimate"
            role="status"
            aria-live="polite"
            aria-label="따릉이 단순 주행 예상"
          >
            <span>대여소 사이 예상</span>
            <strong>{formatDuration(state.data.rideEstimate.durationSeconds)}</strong>
            <p>{formatDistance(state.data.rideEstimate.distanceMeters)} · 시속 {state.data.rideEstimate.assumedSpeedKph}km 기준</p>
          </div>
          <div className="bike-station-grid">
            <StationGroup
              heading="출발 대여소"
              primary={state.pickup}
              alternatives={state.data.pickupStations.filter((station) => station.stationId !== state.pickup.stationId).slice(0, 3)}
              pointLabel="출발지"
            />
            <StationGroup
              heading="반납 대여소"
              primary={state.returnStation}
              alternatives={state.data.returnStations.filter((station) => station.stationId !== state.returnStation.stationId).slice(0, 3)}
              pointLabel="목적지"
            />
          </div>
          <DataSource data={state.data} speedKph={state.data.rideEstimate.assumedSpeedKph} />
        </>
      )}
    </section>
  );
}
