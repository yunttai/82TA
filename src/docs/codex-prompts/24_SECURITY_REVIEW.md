# 24. 보안·개인정보 리뷰

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 큰 기능/통합/릴리스 전

```text
$platform-release-gate

[범위]의 보안·개인정보 리뷰를 수행해줘. 먼저 findings만 작성한다.

검증: root/nested AGENTS 경계, auth/IDOR/CSRF/CORS/CSP, service-to-service auth, SSRF/egress allowlist, API key, GCE edge/rate/Denial-of-Wallet, exact location/logs/retention/deletion, DB/GCS/Redis encryption, model artifact/hash/pickle, mapping/data poisoning, dependency/container/IaC/SBOM, admin/audit/rollback.

각 finding에 severity, exploit/impact, evidence, owner, fix, retest를 기록하고 release blocker를 명시한다.
```
