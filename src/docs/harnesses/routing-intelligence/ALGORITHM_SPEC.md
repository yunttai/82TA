# Routing Algorithm Specification

## 1. Objective

각 candidate `r`에 대해:

```text
T50(r)          P50 total duration
T90(r)          P90 total duration
CtaxiUpper(r)   sum of taxi leg upper cost
Ctotal(r)       total fare
Walk(r)         walk seconds
Transfers(r)    transfer count
Risk(r)         reliability/failure measure
```

Feasible set:

```text
F(B) = { r |
  CtaxiUpper(r) <= B
  and Walk(r) <= maxWalk
  and Transfers(r) <= maxTransfers
  and TaxiLegs(r) <= maxTaxiLegs
}
```

## 2. Time-Dependent Propagation

```text
nextStart = currentArrival + wait + transferBuffer
nextArrival = nextStart + travelTime(nextStart, realtime, confidence)
```

앞 leg 지연으로 bus candidate·transit connection이 바뀌면 뒤 leg를 재평가한다.

## 3. Patterns

- TRANSIT_ONLY
- TAXI_TRANSIT
- TRANSIT_TAXI
- TAXI_TRANSIT_TAXI
- TAXI_ONLY
- UPSTREAM_STOP_TAXI_TRANSIT
- TRANSIT_TAXI_BRIDGE_TRANSIT

## 4. Candidate Pipeline

1. transit baseline top 5
2. origin access hubs max 12
3. destination egress hubs max 12
4. upstream candidates per route max 5
5. coarse combinations max 120
6. exact taxi max 30
7. full Bus Intelligence max 16
8. pre-Pareto max 20
9. user result max 4

모든 숫자는 versioned config다.

## 5. Coarse Pruning

- straight/estimated taxi cost clearly exceeds budget
- service unavailable at propagated time
- constraints exceeded
- duplicate topology
- negative transfer margin
- baseline보다 time/cost/risk 모두 나쁨
- mapping impossible and enrichment mandatory

## 6. Bus Wait

차량 `i`의 boardability proxy `b_i`와 arrival `A_i`:

```text
P(board at 1) = b1
P(board at 2) = (1-b1)*b2
P(board at 3) = (1-b1)*(1-b2)*b3
```

Expected/P90 boarding time을 계산한다. 평가 window 밖 tail은 historical headway로 보수 처리한다.

일반버스 crowded는 seat-failure wait에 직접 사용하지 않는다.

## 7. Transfer

```text
available = nextDeparture - previousArrival
required = walk + stationInternal + boardingBuffer
margin50 = available50 - required50
margin90 = conservativeAvailable - conservativeRequired
```

margin<0 제거. low margin은 stable에서 강한 penalty.

## 8. Taxi Dispatch

Driving duration과 별도 WAIT component다. 초기에는 region/time distribution이며 `MODEL_PREDICTED/HISTORICAL_PROXY`로 표시한다.

## 9. Pareto

A가 B의 다음 값을 모두 같거나 개선하고 하나 이상 엄격 개선하면 B 제거:

- T50
- T90
- taxi upper
- walk
- transfer risk

작은 차이는 versioned epsilon dominance.

## 10. Ranking

- FASTEST: min T50, tie reliability/transfer/walk
- STABLE: min T90 under reliability floor
- EFFICIENT: Pareto marginal saved time / added taxi cost
- TRANSIT_ONLY: taxi upper=0인 최상 후보

## 11. Determinism

Replay input:

- canonical request
- normalized provider snapshots
- clock
- mapping version
- model versions
- ranking policy
- feature flags

같은 bundle은 같은 route keys·ranking·reason을 생성해야 한다.
