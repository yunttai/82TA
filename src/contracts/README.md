# Shared Contracts

이 디렉터리는 두 하네스가 사용하는 기계 판독 가능한 단일 계약 원본이다.

```text
openapi/        Public Service API, Private Routing API, common schema, canonical examples
database/       Service DB, Routing DB, ownership, migration policy
events/         비동기 domain event contract
codes/          reason, warning, error, enum registry
compatibility/  versioning·breaking change 정책
traceability/   requirement→contract→test 연결
ownership/      workstream path·DB 소유권
interfaces/     Service↔Routing handoff 경계
versions/       platform contract·policy version
harness/        두 하네스 registry와 shared context 규칙
```

`CONTEXT_MANIFEST.json`은 canonical 파일 목록과 소유권을 정의하고, `CONTRACT_LOCK.json`은 SHA-256을 고정한다.

## 검증

```bash
python src/scripts/verify_contract_lock.py
python src/scripts/validate_openapi.py
python src/scripts/validate_openapi_examples.py
python src/scripts/validate_harness_registry.py
```

승인된 공통 계약 변경이 완료된 경우에만:

```bash
python src/scripts/update_contract_lock.py --approved-change
```

lock 갱신 전에 ADR, examples, generated client 영향, DB migration, consumer/provider contract test, 양쪽 QA와 changelog를 완료한다.
