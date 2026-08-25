# 14. 승인된 계약 변경 적용

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 13번 승인 후

```text
$shared-contract-governance

승인된 변경안을 적용해줘.

승인된 change request: [경로/내용]

- 승인 범위를 재확인한다.
- PRD/acceptance, OpenAPI, DBML, events, code registry, examples, compatibility, traceability를 atomic하게 수정한다.
- generated clients를 src/generated에 재생성한다.
- producer/consumer tests와 migrations를 양쪽에 반영한다.
- contractVersion/contextVersion 정책을 적용한다.
- 두 담당자 승인 evidence가 있은 뒤에만 update_contract_lock.py --approved-change를 실행한다.
- 양쪽 snapshot과 parity를 검증한다.
- STATUS/HANDOFF/changelog를 갱신한다.
```
