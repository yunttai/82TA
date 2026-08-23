# 33. V2 실시간 재추천 시작

**사용 시점:** Release 1 이후

```text
$shared-contract-governance

V2 실시간 재추천 기능의 contract-first 설계를 시작해줘. 즉시 구현하지 말고 proposal부터 작성한다.

요구: current journey state, current location, completed legs, actual taxi spend, remaining budget, delays/boarding failure, reroute result, route-switch hysteresis, push/notification, location consent/background handling.

- Service/Routing 책임을 분리한다.
- identity는 Routing에 보내지 않는다.
- 위치 frequency/retention/privacy/battery를 정의한다.
- contract/events/DBML/state machine/security/SLO/cost 영향을 작성한다.
- 5분 이득 또는 기존 경로 실패 위험 등 switching policy를 버전화한다.
- Release 1 API compatibility와 migration을 제안한다.
```
