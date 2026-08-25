# 11. 경로 최적화 알고리즘 개발

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** candidate/time/budget/Pareto

```text
$route-optimizer-delivery

다음 Routing 알고리즘 기능을 구현해줘: [기능].

- canonical request와 Provider/Bus Intelligence typed input만 사용한다.
- 허용 pattern과 후보 cap을 지킨다.
- 각 leg는 앞 leg 종료시각으로 재평가한다.
- taxi dispatch wait, transit wait, transfer buffer, Bus expected wait를 분리한다.
- strict mode는 taxi leg upper cost 합이 budget 이하만 허용한다.
- transfer feasibility, epsilon Pareto, duplicate removal, FASTEST/STABLE/EFFICIENT/PUBLIC_TRANSIT_ONLY를 검증한다.
- reason/warning/provenance/ranking version을 남긴다.
- property test와 deterministic replay를 추가한다.
- 6.5초 내부 budget을 측정한다.
```
