import { useEffect, useId, useRef, useState } from "react";

import {
  reverseGeocode,
  suggestPlaces,
  type PlaceRef,
} from "../../shared/api/publicService";

interface PlaceFieldProps {
  label: string;
  value: string;
  allowCurrentLocation?: boolean;
  disabled?: boolean;
  onLabelChange: (value: string) => void;
  onPlaceSelected: (place: PlaceRef) => void;
}

type PlaceStatus = "IDLE" | "LOADING" | "EMPTY" | "RATE_LIMITED" | "UNAVAILABLE";
type LocationStatus = "IDLE" | "LOADING" | "DENIED" | "TIMEOUT" | "INSECURE" | "UNAVAILABLE";

function browserLocation(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("Geolocation unavailable"));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: false,
      maximumAge: 60_000,
      timeout: 8_000,
    });
  });
}

export function PlaceField({
  label,
  value,
  allowCurrentLocation = false,
  disabled = false,
  onLabelChange,
  onPlaceSelected,
}: PlaceFieldProps) {
  const listboxId = useId();
  const requestSequence = useRef(0);
  const [items, setItems] = useState<PlaceRef[]>([]);
  const [status, setStatus] = useState<PlaceStatus>("IDLE");
  const [locationStatus, setLocationStatus] = useState<LocationStatus>("IDLE");
  const [expanded, setExpanded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  useEffect(() => {
    const query = value.trim();
    const sequence = ++requestSequence.current;
    if (!dirty || query.length < 2) {
      setItems([]);
      setExpanded(false);
      setStatus("IDLE");
      return undefined;
    }

    setStatus("LOADING");
    setItems([]);
    setActiveIndex(-1);
    const timer = window.setTimeout(() => {
      void suggestPlaces(query)
        .then(({ data, response }) => {
          if (sequence !== requestSequence.current) return;
          if (!response.ok || data === undefined) {
            setStatus(response.status === 429 ? "RATE_LIMITED" : "UNAVAILABLE");
            setItems([]);
            return;
          }
          setItems(data.items);
          setStatus(data.items.length === 0 ? "EMPTY" : "IDLE");
          setExpanded(data.items.length > 0);
          setActiveIndex(data.items.length > 0 ? 0 : -1);
        })
        .catch(() => {
          if (sequence === requestSequence.current) {
            setStatus("UNAVAILABLE");
            setItems([]);
          }
        });
    }, 300);

    return () => window.clearTimeout(timer);
  }, [dirty, value]);

  async function useCurrentLocation() {
    if (window.isSecureContext === false) {
      setLocationStatus("INSECURE");
      return;
    }
    setLocationStatus("LOADING");
    try {
      const position = await browserLocation();
      const coordinate = {
        lon: position.coords.longitude,
        lat: position.coords.latitude,
      };
      const { data, response } = await reverseGeocode(coordinate);
      if (response.ok && data !== undefined) {
        onPlaceSelected(data);
      } else {
        onPlaceSelected({ displayName: "현재 위치(주소 확인 불가)", coordinate });
      }
      setLocationStatus("IDLE");
      setDirty(false);
      setExpanded(false);
    } catch (error) {
      const code = typeof error === "object" && error !== null && "code" in error ? error.code : undefined;
      setLocationStatus(code === 1 ? "DENIED" : code === 3 ? "TIMEOUT" : "UNAVAILABLE");
    }
  }

  function selectPlace(place: PlaceRef) {
    onPlaceSelected(place);
    setDirty(false);
    setExpanded(false);
    setActiveIndex(-1);
  }

  return (
    <div className="place-combobox">
      <label className="field field-wide">
        <span>{label}</span>
        <input
          role="combobox"
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded={expanded}
          aria-activedescendant={expanded && activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined}
          aria-describedby={status === "UNAVAILABLE" ? `${listboxId}-status` : undefined}
          autoComplete="off"
          value={value}
          disabled={disabled}
          onChange={(event) => {
            setDirty(true);
            onLabelChange(event.currentTarget.value);
            setExpanded(true);
          }}
          onFocus={() => setExpanded(items.length > 0)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setExpanded(false);
              setActiveIndex(-1);
              return;
            }
            if (event.key === "ArrowDown" && items.length > 0) {
              event.preventDefault();
              setExpanded(true);
              setActiveIndex((current) => Math.min(current + 1, items.length - 1));
              return;
            }
            if (event.key === "ArrowUp" && items.length > 0) {
              event.preventDefault();
              setExpanded(true);
              setActiveIndex((current) => Math.max(current - 1, 0));
              return;
            }
            if (event.key === "Enter" && expanded && activeIndex >= 0 && items[activeIndex]) {
              event.preventDefault();
              selectPlace(items[activeIndex]);
            }
          }}
          required
        />
      </label>

      {allowCurrentLocation && (
        <button
          className="location-button"
          type="button"
          disabled={disabled || locationStatus === "LOADING"}
          onClick={() => void useCurrentLocation()}
        >
          {locationStatus === "LOADING" ? "현재 위치 확인 중…" : "현재 위치 사용"}
        </button>
      )}

      {status === "LOADING" && <p className="place-status" role="status">장소를 찾는 중…</p>}
      {status === "EMPTY" && <p className="place-status" role="status">검색 결과가 없습니다. 주소를 더 구체적으로 입력해 주세요.</p>}
      {status === "RATE_LIMITED" && <p className="place-status" role="status">장소 검색 요청이 많습니다. 잠시 기다린 뒤 다시 시도해 주세요.</p>}
      {status === "UNAVAILABLE" && (
        <p className="place-status" id={`${listboxId}-status`} role="status">
          장소 추천을 사용할 수 없습니다. 아래 좌표 직접 입력을 이용해 주세요.
        </p>
      )}
      {locationStatus !== "IDLE" && locationStatus !== "LOADING" && (
        <p className="place-status" role="alert">{
          locationStatus === "DENIED" ? "위치 권한이 꺼져 있습니다. 브라우저 설정을 확인하거나 장소를 검색해 주세요."
            : locationStatus === "TIMEOUT" ? "위치 확인이 오래 걸리고 있습니다. 다시 시도하거나 장소를 검색해 주세요."
              : locationStatus === "INSECURE" ? "현재 위치는 HTTPS 연결에서만 사용할 수 있습니다. 장소를 직접 검색해 주세요."
                : "현재 위치를 확인할 수 없습니다. 장소 검색이나 지도 선택을 이용해 주세요."
        }</p>
      )}

      {expanded && items.length > 0 && (
        <ul className="place-suggestions" id={listboxId} role="listbox" aria-label={`${label} 검색 결과`}>
          {items.map((item, index) => (
            <li key={`${item.provider ?? "place"}-${item.providerPlaceId ?? `${item.coordinate.lon},${item.coordinate.lat}`}`}>
              <button
                id={`${listboxId}-option-${index}`}
                type="button"
                role="option"
                aria-selected={index === activeIndex}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => {
                  selectPlace(item);
                }}
              >
                <strong>{item.displayName}</strong>
                {item.address && <span>{item.address}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
