# 09. Kakao↔GBIS 매핑

**사용 시점:** 노선/정류장/방향 매핑

```text
$transport-mapping-delivery

[대상 경로/노선]의 Provider transit 결과를 GBIS canonical route/stop/direction에 매핑하는 기능을 구현·검증해줘.

- 이름만으로 확정하지 않는다.
- 노선 유형, 승하차 정류장, 좌표, sequence, direction, 기종점, geometry를 evidence로 사용한다.
- gold fixture와 ambiguous/opposite/A-B branch/turning point 사례를 만든다.
- HIGH/MEDIUM/LOW threshold와 review queue를 구현한다.
- LOW는 Bus Intelligence 미적용이다.
- mapping version/evidence/validity/audit를 저장한다.
- coverage와 HIGH precision을 보고한다.
```
