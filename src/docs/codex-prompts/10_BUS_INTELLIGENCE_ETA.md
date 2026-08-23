# 10. Bus Intelligence/ETA 개발

**사용 시점:** ETA/Seat/Boardability/Wait

```text
$bus-intelligence-delivery
$routing-data-mlops

Bus Intelligence의 다음 범위를 개발·검증해줘: [ETA/Seat Risk/Boardability/Expected Wait/전체].

- 기존 데이터 inventory와 label policy를 먼저 감사한다.
- 동일 vehicle trip과 target station/time 실제 미래관측만 label로 사용한다.
- 미래관측 없음은 NULL/unobserved다.
- ETA와 Seat model을 분리한다.
- time/trip grouped split, baseline, route/time/horizon slice, calibration/interval을 검증한다.
- train/serve feature parity, safe artifact, registry, shadow/canary/rollback을 구현한다.
- 일반버스와 좌석버스 정책을 분리한다.
- 결과가 expected/P90 bus wait와 route ranking에 실제 영향을 주는 replay를 제시한다.
- 데이터 부족은 ACTIVE로 과장하지 말고 SHADOW/UNVERIFIED로 남긴다.
```
