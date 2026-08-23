# 20. 1번·2번 최초 통합

**사용 시점:** 두 작업흐름을 처음 실제 연결

```text
$integration-coherence-qa

Service Product와 Routing & Intelligence를 처음 통합해줘.

- 두 HANDOFF와 context snapshot을 읽고 parity가 아니면 중단한다.
- integration WORKPLAN을 작성하고 contract-steward, architecture-auditor, integration-qa 및 필요한 양쪽 QA에 독립 검증을 위임한다.
- Service HttpRoutingGateway를 실제 Private API에 연결한다.
- service JWT, deadline, idempotency, correlation, timeout을 검증한다.
- canonical mock/replay와 real response parity를 비교한다.
- Public projection이 내부 raw/debug/user-identity 경계를 지키는지 확인한다.
- COMPLETE/PARTIAL/NO_FEASIBLE/503/504를 E2E로 검증한다.
- DB ownership, no cross-query, no identity in Routing을 확인한다.
- R1~R4 smoke/replay와 P95를 실행한다.
- findings를 owner에게 고치게 한 뒤 최종 PASS/FAIL/UNVERIFIED를 작성한다.
```
