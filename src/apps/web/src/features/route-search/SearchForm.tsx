import { useEffect, useId, useState, type FormEvent } from "react";

import { PlaceField } from "../place-search/PlaceField";
import { MapCoordinatePicker } from "../place-search/MapCoordinatePicker";
import type {
  PlaceRef,
  PublicCapabilities,
  PublicRouteSearchRequest,
  UserPreferences,
} from "../../shared/api/publicService";

type Optimization = PublicRouteSearchRequest["preferences"]["optimization"];
type AllowedMode = NonNullable<PublicRouteSearchRequest["preferences"]["allowedModes"]>[number];

const canonicalModes: readonly AllowedMode[] = ["WALK", "WAIT", "TRANSFER", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"];
const budgetPresetAmounts = [0, 5000, 10000, 20000] as const;
const modeLabels: Readonly<Record<AllowedMode, string>> = {
  WALK: "도보", WAIT: "대기", TRANSFER: "환승 이동", TAXI: "택시",
  BUS: "버스", SUBWAY: "지하철", GTX: "GTX", TRAIN: "기차",
};

export interface SearchDraft {
  originName: string;
  originLongitude: string;
  originLatitude: string;
  destinationName: string;
  destinationLongitude: string;
  destinationLatitude: string;
  departureTiming: "NOW" | "SCHEDULED";
  departureTime: string;
  departureType: PublicRouteSearchRequest["departure"]["type"];
  arrivalDeadline: string;
  taxiBudgetKrw: string;
  maxWalkMinutes: string;
  maxTransfers: string;
  maxTaxiLegs: string;
  allowTaxiBridge: boolean;
  avoidHighBusSeatRisk: boolean;
  avoidStairs: boolean;
  wheelchair: boolean;
  saveToHistory: boolean;
  allowedModes: AllowedMode[];
  optimization: Optimization;
}

interface SearchFormProps {
  busy: boolean;
  offline?: boolean;
  errors: readonly string[];
  capabilities?: PublicCapabilities | null;
  initialPreferences?: UserPreferences | null;
  initialTaxiBudget?: number;
  onSubmit: (draft: SearchDraft) => void;
}

function localDateTimeDefault(): string {
  const date = new Date(Date.now() + 5 * 60 * 1000);
  const koreaTime = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  return koreaTime.toISOString().slice(0, 16);
}

export function SearchForm({ busy, offline = false, errors, capabilities, initialPreferences = null, initialTaxiBudget, onSubmit }: SearchFormProps) {
  const errorId = useId();
  const [userEdited, setUserEdited] = useState(false);
  const startingTaxiBudget = initialTaxiBudget ?? 10000;
  const [selectedBudgetPreset, setSelectedBudgetPreset] = useState<number | null>(budgetPresetAmounts.includes(startingTaxiBudget as (typeof budgetPresetAmounts)[number]) ? startingTaxiBudget : null);
  const [draft, setDraft] = useState<SearchDraft>({
    originName: "명지대학교 자연캠퍼스",
    originLongitude: "127.187456",
    originLatitude: "37.222345",
    destinationName: "판교역",
    destinationLongitude: "127.111159",
    destinationLatitude: "37.394761",
    departureTiming: "NOW",
    departureTime: localDateTimeDefault(),
    departureType: "DEPART_AT",
    arrivalDeadline: "",
    taxiBudgetKrw: String(startingTaxiBudget),
    maxWalkMinutes: "15",
    maxTransfers: "3",
    maxTaxiLegs: "2",
    allowTaxiBridge: true,
    avoidHighBusSeatRisk: false,
    avoidStairs: false,
    wheelchair: false,
    saveToHistory: false,
    allowedModes: [...canonicalModes],
    optimization: "BALANCED",
  });

  useEffect(() => {
    if (initialPreferences === null || userEdited || initialTaxiBudget !== undefined) return;
    setSelectedBudgetPreset(budgetPresetAmounts.includes(initialPreferences.defaultTaxiBudget as (typeof budgetPresetAmounts)[number])
      ? initialPreferences.defaultTaxiBudget
      : null);
    setDraft((current) => ({
      ...current,
      taxiBudgetKrw: String(initialPreferences.defaultTaxiBudget),
      maxWalkMinutes: String(initialPreferences.maxWalkSeconds / 60),
      maxTransfers: String(initialPreferences.maxTransfers),
      maxTaxiLegs: String(initialPreferences.maxTaxiLegs),
      optimization: initialPreferences.optimizationProfile,
      avoidStairs: initialPreferences.accessibility?.avoidStairs ?? false,
      wheelchair: initialPreferences.accessibility?.wheelchair ?? false,
    }));
  }, [initialPreferences, initialTaxiBudget, userEdited]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (offline) return;
    onSubmit({
      ...draft,
      allowTaxiBridge: capabilities?.features?.taxiBridge === true && draft.allowTaxiBridge,
      avoidHighBusSeatRisk: capabilities?.features?.busSeatRisk === true && draft.avoidHighBusSeatRisk,
    });
  }

  function swapPlaces() {
    setDraft({
      ...draft,
      originName: draft.destinationName,
      originLongitude: draft.destinationLongitude,
      originLatitude: draft.destinationLatitude,
      destinationName: draft.originName,
      destinationLongitude: draft.originLongitude,
      destinationLatitude: draft.originLatitude,
    });
  }

  return (
    <form className="search-form" onSubmit={submit} onChangeCapture={() => setUserEdited(true)} onClickCapture={() => setUserEdited(true)} aria-describedby={errors.length > 0 ? errorId : undefined}>
      <fieldset disabled={busy}>
        <legend className="sr-only">출발지와 목적지</legend>
        <div className="route-endpoints">
          <div className="route-rail" aria-hidden="true"><i /><span /><i /></div>
          <div className="route-fields">
            <PlaceField
              label="출발지"
              value={draft.originName}
              allowCurrentLocation
              disabled={busy}
              onLabelChange={(originName) => setDraft({ ...draft, originName })}
              onPlaceSelected={(place: PlaceRef) => setDraft({
                ...draft,
                originName: place.displayName,
                originLongitude: String(place.coordinate.lon),
                originLatitude: String(place.coordinate.lat),
              })}
            />

            <PlaceField
              label="목적지"
              value={draft.destinationName}
              disabled={busy}
              onLabelChange={(destinationName) => setDraft({ ...draft, destinationName })}
              onPlaceSelected={(place: PlaceRef) => setDraft({
                ...draft,
                destinationName: place.displayName,
                destinationLongitude: String(place.coordinate.lon),
                destinationLatitude: String(place.coordinate.lat),
              })}
            />
          </div>
          <button className="swap-button" type="button" disabled={busy} onClick={swapPlaces} aria-label="출발지와 목적지 바꾸기">⇅</button>
        </div>

        <details className="input-map-details">
          <summary>지도에서 직접 위치 선택</summary>
          <MapCoordinatePicker
            origin={{ displayName: draft.originName, coordinate: { lon: Number(draft.originLongitude), lat: Number(draft.originLatitude) } }}
            destination={{ displayName: draft.destinationName, coordinate: { lon: Number(draft.destinationLongitude), lat: Number(draft.destinationLatitude) } }}
            disabled={busy}
            onPlaceSelected={(target, place) => setDraft(target === "ORIGIN" ? {
              ...draft,
              originName: place.displayName,
              originLongitude: String(place.coordinate.lon),
              originLatitude: String(place.coordinate.lat),
            } : {
              ...draft,
              destinationName: place.displayName,
              destinationLongitude: String(place.coordinate.lon),
              destinationLatitude: String(place.coordinate.lat),
            })}
          />
        </details>

        <div className="form-grid form-grid-spaced">
          <fieldset className="choice-fieldset">
            <legend>출발 시간</legend>
            <label className="check-field"><input type="radio" name="departureTiming" checked={draft.departureTiming === "NOW"} onChange={() => setDraft({ ...draft, departureTiming: "NOW" })} /><span>지금 출발</span></label>
            <label className="check-field"><input type="radio" name="departureTiming" checked={draft.departureTiming === "SCHEDULED"} onChange={() => setDraft({ ...draft, departureTiming: "SCHEDULED" })} /><span>지정 시각 출발</span></label>
          </fieldset>
          <label className="field" aria-disabled={draft.departureTiming === "NOW"}>
            <span>지정 출발 시각 · 한국 시간</span>
            <input
              name="departureTime"
              type="datetime-local"
              value={draft.departureTime}
              onChange={(event) => setDraft({ ...draft, departureTime: event.currentTarget.value })}
              disabled={draft.departureTiming === "NOW"}
              required={draft.departureTiming === "SCHEDULED"}
            />
          </label>
          <div className="budget-section field-wide">
            <span className="budget-title">요금 상한</span>
            <div className="budget-presets" role="group" aria-label="택시 요금 빠른 선택">
              {([[0, "무관"], [5000, "5천원"], [10000, "1만원"], [20000, "2만원"]] as const).map(([amount, label]) => (
                <button key={amount} type="button" aria-pressed={selectedBudgetPreset === amount} onClick={() => {
                  setSelectedBudgetPreset(amount);
                  setDraft({ ...draft, taxiBudgetKrw: String(amount) });
                }}>
                  {label}
                </button>
              ))}
            </div>
            <label className="field budget-field">
              <span>직접 입력</span>
              <span className="input-suffix">
                <input
                  name="taxiBudgetKrw"
                  inputMode="numeric"
                  min={0}
                  max={500000}
                  step={1}
                  value={draft.taxiBudgetKrw}
                  onFocus={() => setSelectedBudgetPreset(null)}
                  onChange={(event) => {
                    setSelectedBudgetPreset(null);
                    setDraft({ ...draft, taxiBudgetKrw: event.currentTarget.value });
                  }}
                  required
                />
                <span>원</span>
              </span>
            </label>
          </div>
        </div>

        <details className="details-panel">
          <summary>세부 조건</summary>
          <div className="form-grid details-grid">
            <label className="field field-wide deadline-field">
              <span>도착 마감 시각(선택) · 한국 시간</span>
              <input
                name="arrivalDeadline"
                type="datetime-local"
                value={draft.arrivalDeadline}
                onChange={(event) => setDraft({ ...draft, arrivalDeadline: event.currentTarget.value })}
              />
              <small>출발 시각을 역산하지 않고 Service를 통해 Routing에 그대로 전달합니다.</small>
            </label>
            <label className="field">
              <span>최대 도보</span>
              <span className="input-suffix">
                <input
                  name="maxWalkMinutes"
                  inputMode="numeric"
                  value={draft.maxWalkMinutes}
                  onChange={(event) => setDraft({ ...draft, maxWalkMinutes: event.currentTarget.value })}
                />
                <span>분</span>
              </span>
            </label>
            <label className="field">
              <span>최대 환승</span>
              <select
                name="maxTransfers"
                value={draft.maxTransfers}
                onChange={(event) => setDraft({ ...draft, maxTransfers: event.currentTarget.value })}
              >
                {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((count) => <option key={count} value={count}>{count}회</option>)}
              </select>
            </label>
            <label className="field">
              <span>최대 택시 구간</span>
              <select
                name="maxTaxiLegs"
                value={draft.maxTaxiLegs}
                onChange={(event) => setDraft({ ...draft, maxTaxiLegs: event.currentTarget.value })}
              >
                {[0, 1, 2, 3].map((count) => <option key={count} value={count}>{count}개</option>)}
              </select>
            </label>
            <label className="field">
              <span>추천 기준</span>
              <select
                name="optimization"
                value={draft.optimization}
                onChange={(event) => {
                  const value = event.currentTarget.value;
                  if (value === "FASTEST" || value === "STABLE" || value === "EFFICIENT" || value === "BALANCED") {
                    setDraft({ ...draft, optimization: value });
                  }
                }}
              >
                <option value="BALANCED">균형</option>
                <option value="FASTEST">빠른 도착</option>
                <option value="STABLE">안정적인 도착</option>
                <option value="EFFICIENT">비용 효율</option>
              </select>
            </label>
          </div>
          <div className="check-list">
            <fieldset className="mode-fieldset">
              <legend>허용 교통수단</legend>
              <div className="mode-grid">
                {canonicalModes.map((mode) => (
                  <label className="check-field" key={mode}>
                    <input
                      type="checkbox"
                      checked={draft.allowedModes.includes(mode)}
                      onChange={(event) => setDraft({
                        ...draft,
                        allowedModes: event.currentTarget.checked
                          ? [...draft.allowedModes, mode]
                          : draft.allowedModes.filter((item) => item !== mode),
                      })}
                    />
                    <span>{modeLabels[mode]}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="check-field">
              <input
                type="checkbox"
                checked={capabilities?.features?.taxiBridge === true && draft.allowTaxiBridge}
                disabled={capabilities?.features?.taxiBridge !== true}
                onChange={(event) => setDraft({ ...draft, allowTaxiBridge: event.currentTarget.checked })}
              />
              <span>대중교통 사이 짧은 택시 이동 허용</span>
            </label>
            {capabilities?.features?.taxiBridge !== true && <p className="capability-help">택시 연결은 {capabilities === null ? "지원 여부 확인 중" : "현재 미지원"}이라 선택할 수 없습니다.</p>}
            <label className="check-field">
              <input
                type="checkbox"
                checked={capabilities?.features?.busSeatRisk === true && draft.avoidHighBusSeatRisk}
                disabled={capabilities?.features?.busSeatRisk !== true}
                onChange={(event) => setDraft({ ...draft, avoidHighBusSeatRisk: event.currentTarget.checked })}
              />
              <span>좌석 부족 위험이 높은 버스 피하기</span>
            </label>
            {capabilities?.features?.busSeatRisk !== true && <p className="capability-help">좌석 위험 회피는 {capabilities === null ? "지원 여부 확인 중" : "현재 미지원"}이라 선택할 수 없습니다. 위험이 낮다는 뜻은 아닙니다.</p>}
            <label className="check-field">
              <input
                type="checkbox"
                checked={draft.avoidStairs}
                onChange={(event) => setDraft({ ...draft, avoidStairs: event.currentTarget.checked })}
              />
              <span>계단이 있는 경로 피하기</span>
            </label>
            <label className="check-field">
              <input
                type="checkbox"
                checked={draft.wheelchair}
                onChange={(event) => setDraft({ ...draft, wheelchair: event.currentTarget.checked })}
              />
              <span>휠체어 접근 가능한 경로 우선</span>
            </label>
            <label className="check-field">
              <input
                type="checkbox"
                checked={draft.saveToHistory}
                onChange={(event) => setDraft({ ...draft, saveToHistory: event.currentTarget.checked })}
              />
              <span>동의한 계정의 검색 기록에 저장</span>
            </label>
          </div>
        </details>
      </fieldset>

      {errors.length > 0 && (
        <div className="form-errors" id={errorId} role="alert">
          <strong>입력을 다시 확인해 주세요.</strong>
          <ul>{errors.map((error) => <li key={error}>{error}</li>)}</ul>
        </div>
      )}

      <button className="search-button" type="submit" disabled={busy || offline}>
        {busy ? "경로를 비교하는 중…" : offline ? "연결 후 경로 검색 가능" : "내 예산으로 경로 찾기"}
      </button>
      {offline && <p className="offline-form-help" role="status">오프라인에서는 경로 검색을 보낼 수 없습니다. 연결 후 입력을 확인하고 직접 검색해 주세요.</p>}
      <p className="form-footnote">실제 택시 요금과 도착 시각은 교통 상황에 따라 달라질 수 있습니다.</p>
    </form>
  );
}
