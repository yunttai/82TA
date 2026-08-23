# 26. 기존 3주 데이터 감사

**사용 시점:** DB/통계를 제공받았을 때

```text
$routing-data-mlops

제공된 기존 BusCrowdRisk 데이터/DB를 수정하지 말고 감사해줘.

- schema/hash/기간/행/노선/방향/차량/trip/time slice
- arrival/location/seat missing, duplicate, out-of-order, station sequence
- target observation coverage와 미래관측 없음 처리
- capacity evidence
- weather/traffic/context coverage
- current model diagnostics/calibration/artifact safety
- leakage 위험

결과를 데이터 inventory, quality report, migration reconciliation, model feasibility, 추가 수집 우선순위로 작성한다. 수치를 추측하지 않는다.
```
