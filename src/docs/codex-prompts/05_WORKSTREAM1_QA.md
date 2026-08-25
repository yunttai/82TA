# 05. 1번 단독 QA

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 2번과 합치기 전 Service 검증

```text
$service-incremental-qa

Service Product 작업흐름을 검증해줘. 먼저 코드를 수정하지 말고 findings를 작성하라.

검증: Public OpenAPI↔Django, Django↔generated TS client, client↔React, null/unknown/unsupported, route 값 재계산 금지, auth/IDOR/CSRF/rate limit, 위치/secret 로그, Service DBML↔models/migrations, Stub/Replay, accessibility/responsive/PWA, unit/contract/E2E.

각 finding에 severity, 파일/심볼, 재현, requirement/contract, owner, retest를 기록하고 PASS/CONDITIONAL/FAIL/UNVERIFIED로 판정하라.
```
