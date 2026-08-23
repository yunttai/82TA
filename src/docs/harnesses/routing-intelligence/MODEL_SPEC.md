# Bus Intelligence Model Specification

## 1. 모델 분리

| 구성 | 출력 |
|---|---|
| ETA Model | target stop ETA distribution |
| Seat Risk Model | target stop no-seat·low-seat probability |
| Boardability Rules/Model | seat availability 기반 proxy |
| Expected Wait | candidate vehicle distribution |
| Confidence | freshness·mapping·coverage·model confidence |

ETA와 Seat를 한 모델로 합치지 않는다.

## 2. Trip Identity

```text
route_id + direction + vehicle token + service_date
+ inferred trip start + station sequence reset
```

회차·차고지·대체차량을 분리한다.

## 3. ETA

Target: prediction timestamp부터 target stop 실제 arrival observation까지 seconds.

Features:

- route/type/direction
- current/target sequence, remaining stops
- recent 1/3/5 segment time
- historical segment time
- headway/front vehicle gap
- time/day/holiday
- weather
- GITS traffic/incident optional
- freshness/missing flags

Baseline: LightGBM regression. Interval: quantile or conformal.

Metrics: MAE, Median AE, P90 AE, interval coverage, route/time/weather slices.

## 4. Seat Risk

Targets:

- P(remainSeat=0 at target stop)
- P(remainSeat<=2)
- optional <=5

Future observation missing => NULL and excluded.

Features:

- current seats/crowded/capacity confidence
- recent seat delta
- target remaining stops/progress
- route/direction/headway
- time/day/holiday/season
- demand source/quality
- weather/event/traffic ablation
- freshness/missing flags

Metrics: PR-AUC, recall, precision, Brier, ECE, reliability, slices.

## 5. Capacity Registry

Priority:

1. official vehicle data
2. validated vehicle type mapping
3. long-term observed max with evidence
4. route type prior
5. unknown

Value, source, confidence, observation count, validity를 저장한다.

## 6. Demand

Priority:

1. official route-stop-time ridership
2. seat delta signal
3. route historical pattern
4. station daily demand + route evidence
5. low-confidence heuristic

고정 hour ratio와 equal route share는 baseline only.

## 7. Split

금지: random row split, same trip overlap, future leakage.

권장: temporal holdout, trip group split, route/direction slice, unseen date/event, optional route holdout.

## 8. Calibration

- temporal validation
- isotonic vs Platt
- global with slice confidence fallback
- raw probability와 operational decision 분리

## 9. Artifact

- native model binary
- metadata.json
- feature_schema.json
- calibration artifact
- model_card.md
- sha256 and optional signature

Status: REGISTERED→VALIDATED→SHADOW→CANARY→ACTIVE→RETIRED/REJECTED.

## 10. Online Parity

같은 normalized observation과 versioned feature builder를 training/serving에서 사용한다. schema mismatch는 inference를 거절하고 fallback.
