# 29. 판매 가능한 Release Gate

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** Closed Beta/GA 직전

```text
$platform-release-gate
$integration-coherence-qa

[릴리스 버전]을 판매/운영 가능한 release gate로 검증해줘.

- 기능/대표 R1~R4/field test
- contract/context/generated clients
- strict budget, ETA/seat coverage/calibration
- Provider production approval/terms/quota/cost
- P95/availability/partial/fallback
- auth/privacy/location/deletion
- threat model/security scans/SBOM
- GCE HA/backup/restore/rollback/observability/runbooks
- admin/model/mapping audit
- unresolved risks/TBD

PASS, CONDITIONAL, FAIL로 판정하고 blocking items, accepted risks(owner/expiry), rollback, post-release monitoring을 작성한다.
```
