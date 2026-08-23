# Dual Harness Integration Playbook

## 1. 목표

두 하네스가 독립 개발해도 PRD·API·DB·enum·context가 동일하도록 보장하고, 나중에 HTTP 분리 배포 또는 단일 process로 안전하게 합친다.

## 2. 작업 시작

```bash
python src/scripts/validate_repository.py
python src/scripts/verify_contract_lock.py
python src/scripts/snapshot_context.py service-product
# 또는 routing-intelligence
```

실패하면 구현하지 않는다.

## 3. Context Snapshot

각 실행은 다음을 `_workspace/{harness}/00_context_snapshot.json`에 기록한다.

- contextVersion
- contractVersion
- canonical file hash
- source revision
- 실행 시각

통합하려는 두 작업의 snapshot version이 다르면 먼저 contract sync를 수행한다.

## 4. 계약 변경

```text
변경 제안
 -> requirement ID·사용자 가치
 -> ADR
 -> OpenAPI/DBML/codes/examples 변경
 -> compatibility 분석
 -> contract lock 갱신
 -> generated client 갱신
 -> consumer/provider test
 -> 양쪽 QA 승인
 -> 구현
```

## 5. 독립 배포 순서

1. Routing이 optional field를 backward-compatible하게 추가
2. Service generated client 갱신
3. Service projection과 Frontend를 feature flag로 활성화
4. telemetry 확인
5. deprecation 기간 후 old field 제거

## 6. Merge Readiness

- [ ] context snapshot version 동일
- [ ] contract lock 통과
- [ ] OpenAPI breaking diff 없음
- [ ] generated client 최신
- [ ] DBML과 migration 일치
- [ ] 상대 DB 직접 조회 없음
- [ ] user identity가 Routing request에 없음
- [ ] internal sensitive field public redaction
- [ ] replay diff 승인
- [ ] source layout 검증 통과

## 7. HTTP→In-Process 통합

1. Routing domain의 Django 독립 확인
2. `InProcessRoutingGateway` 추가
3. HTTP와 in-process shadow parity replay
4. 일부 staging 요청 전환
5. latency·memory·failure isolation 평가
6. feature flag 확대
7. HTTP deployment 종료 여부 결정
8. DTO와 logical DB ownership은 유지

## 8. 충돌 처리

- code가 contract와 다르면 contract 우선
- workstream 문서가 shared 문서와 다르면 shared 우선
- 상충되는 두 요구가 있으면 삭제하지 않고 ADR에서 명시적으로 결정
- 보안·법률 gate가 기능 요구보다 우선
