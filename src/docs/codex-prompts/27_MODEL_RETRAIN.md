# 27. 모델 재학습·승격

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 데이터 감사 후

```text
$bus-intelligence-delivery
$routing-data-mlops

[ETA/Seat] 모델을 재학습하고 승격 후보를 평가해줘.

- 승인된 snapshot/feature/target version을 고정한다.
- time/trip grouped split과 baselines를 만든다.
- route/time/horizon slices, calibration/interval, coverage, latency를 평가한다.
- train/serve parity와 artifact metadata/hash/model card를 생성한다.
- 기존 ACTIVE 대비 replay/ranking 영향과 regression을 비교한다.
- 기준 미달이면 REGISTERED/SHADOW에 두고 ACTIVE로 승격하지 않는다.
- 승격 시 canary/rollback/monitoring을 준비한다.
```
