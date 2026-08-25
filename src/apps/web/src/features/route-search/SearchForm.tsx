import { useEffect, useId, useState, type FormEvent } from "react";

import { PlaceField } from "../place-search/PlaceField";
import { MapCoordinatePicker } from "../place-search/MapCoordinatePicker";
import { maximumTaxiBudgetKrw, taxiBudgetToExpectedFareCapKrw } from "./fareBudget";
import type {
  PlaceRef,
  PublicCapabilities,
  PublicRouteSearchRequest,
  UserPreferences,
} from "../../shared/api/publicService";

type Optimization = PublicRouteSearchRequest["preferences"]["optimization"];
type AllowedMode = NonNullable<PublicRouteSearchRequest["preferences"]["allowedModes"]>[number];

const canonicalModes: readonly AllowedMode[] = ["WALK", "WAIT", "TRANSFER", "TAXI", "BUS", "SUBWAY", "GTX", "TRAIN"];
const budgetPresetAmounts = [maximumTaxiBudgetKrw, 5000, 10000, 20000] as const;

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
  fareCapUnconstrained: boolean;
  maxWalkMinutes: string;
  maxTransfers: string;
  maxTaxiLegs: string;
  allowTaxiBridge: boolean;
  avoidHighBusSeatRisk: boolean;
  avoidStairs: boolean;
  wheelchair: boolean;
  allowedModes: AllowedMode[];
  optimization: Optimization;
}

interface SearchFormProps {
  busy: boolean;
  offline?: boolean;
  errors: readonly string[];
  capabilities?: PublicCapabilities | null;
  initialPreferences?: UserPreferences | null;
  initialFareCap?: number;
  onSubmit: (draft: SearchDraft) => void;
}

function localDateTimeDefault(): string {
  const date = new Date(Date.now() + 5 * 60 * 1000);
  const koreaTime = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  return koreaTime.toISOString().slice(0, 16);
}

export function SearchForm({ busy, offline = false, errors, capabilities, initialPreferences = null, initialFareCap, onSubmit }: SearchFormProps) {
  const errorId = useId();
  const [userEdited, setUserEdited] = useState(false);
  const startingFareCap = initialFareCap ?? 10000;
  const [selectedBudgetPreset, setSelectedBudgetPreset] = useState<number | null>(budgetPresetAmounts.includes(startingFareCap as (typeof budgetPresetAmounts)[number]) ? startingFareCap : null);
  const [draft, setDraft] = useState<SearchDraft>({
    originName: "",
    originLongitude: "",
    originLatitude: "",
    destinationName: "",
    destinationLongitude: "",
    destinationLatitude: "",
    departureTiming: "NOW",
    departureTime: localDateTimeDefault(),
    departureType: "DEPART_AT",
    arrivalDeadline: "",
    taxiBudgetKrw: String(startingFareCap),
    fareCapUnconstrained: startingFareCap === maximumTaxiBudgetKrw,
    maxWalkMinutes: "120",
    maxTransfers: "8",
    maxTaxiLegs: "3",
    allowTaxiBridge: true,
    avoidHighBusSeatRisk: false,
    avoidStairs: false,
    wheelchair: false,
    allowedModes: [...canonicalModes],
    optimization: "BALANCED",
  });

  useEffect(() => {
    if (initialPreferences === null || userEdited || initialFareCap !== undefined) return;
    const preferredFareCap = taxiBudgetToExpectedFareCapKrw(initialPreferences.defaultTaxiBudget);
    setSelectedBudgetPreset(budgetPresetAmounts.includes(preferredFareCap as (typeof budgetPresetAmounts)[number])
      ? preferredFareCap
      : null);
    setDraft((current) => ({
      ...current,
      taxiBudgetKrw: String(preferredFareCap),
      fareCapUnconstrained: initialPreferences.defaultTaxiBudget === maximumTaxiBudgetKrw,
      optimization: initialPreferences.optimizationProfile,
      avoidStairs: initialPreferences.accessibility?.avoidStairs ?? false,
      wheelchair: initialPreferences.accessibility?.wheelchair ?? false,
    }));
  }, [initialPreferences, initialFareCap, userEdited]);

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
              onLabelChange={(originName) => setDraft({ ...draft, originName, originLongitude: "", originLatitude: "" })}
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
              onLabelChange={(destinationName) => setDraft({ ...draft, destinationName, destinationLongitude: "", destinationLatitude: "" })}
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
            <span className="budget-title">예상 요금 상한</span>
            <div className="budget-presets" role="group" aria-label="예상 요금 상한 빠른 선택">
              {([[maximumTaxiBudgetKrw, "무관"], [5000, "5천원"], [10000, "1만원"], [20000, "2만원"]] as const).map(([amount, label]) => (
                <button key={amount} type="button" aria-pressed={selectedBudgetPreset === amount} onClick={() => {
                  setSelectedBudgetPreset(amount);
                  setDraft({ ...draft, taxiBudgetKrw: String(amount), fareCapUnconstrained: amount === maximumTaxiBudgetKrw });
                }}>
                  {label}
                </button>
              ))}
            </div>
            <label className="field budget-field">
              <span>요금 상한 직접 입력</span>
              <span className="input-suffix">
                <input
                  name="taxiBudgetKrw"
                  inputMode="numeric"
                  min={0}
                  max={500000}
                  step={1}
                  value={selectedBudgetPreset === maximumTaxiBudgetKrw ? "" : draft.taxiBudgetKrw}
                  placeholder={selectedBudgetPreset === maximumTaxiBudgetKrw ? "무관 선택됨" : undefined}
                  onFocus={() => {
                    if (selectedBudgetPreset === maximumTaxiBudgetKrw) setDraft({ ...draft, taxiBudgetKrw: "", fareCapUnconstrained: false });
                    setSelectedBudgetPreset(null);
                  }}
                  onChange={(event) => {
                    setSelectedBudgetPreset(null);
                    setDraft({ ...draft, taxiBudgetKrw: event.currentTarget.value, fareCapUnconstrained: false });
                  }}
                  required={selectedBudgetPreset !== maximumTaxiBudgetKrw}
                />
                <span>원</span>
              </span>
            </label>
          </div>
        </div>

        <div className="check-list primary-search-options">
          <label className="check-field">
            <input
              type="checkbox"
              checked={capabilities?.features?.taxiBridge === true && draft.allowTaxiBridge}
              disabled={capabilities?.features?.taxiBridge !== true}
              onChange={(event) => setDraft({ ...draft, allowTaxiBridge: event.currentTarget.checked })}
            />
            <span>대중교통 사이 짧은 택시 이동 허용</span>
          </label>
        </div>
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
