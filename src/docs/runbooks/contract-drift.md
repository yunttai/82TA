# Runbook: Contract Drift

1. `verify_contract_lock.py` 결과와 변경 파일 확인
2. 의도적 변경인지 unauthorized drift인지 분류
3. 의도적이면 ADR/change request, OpenAPI·DBML·codes·examples 동시 갱신
4. consumer/provider tests
5. version/changelog
6. joint approval 후 lock update
7. generated client 재생성
8. staging compatibility

승인 없는 drift는 원복한다.
