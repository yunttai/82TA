# Service Product Harness Execution Playbook

## 시작

```bash
python src/scripts/validate_repository.py
python src/scripts/snapshot_context.py service-product
```

## 한 기능의 표준 흐름

1. PRD requirement와 Public/Private contract 선택
2. UX 상태·fixture·acceptance 정의
3. Backend producer와 Frontend consumer 병렬 구현
4. Service DB·privacy 영향 검토
5. module 직후 incremental QA
6. mock E2E
7. 실제 Routing response parity
8. security·accessibility·source layout 검증
9. release evidence와 known gap 기록

## 상대 작업흐름 의존

Routing 구현이 없어도 generated private client와 stub/replay로 계속한다. 새 field가 필요하면 Service 임의 schema를 만들지 않고 Contract Change Request를 생성한다.

## 완료 보고 형식

- Requirement IDs
- 변경 파일
- 사용한 contract/context hash
- mock/real integration 상태
- 테스트 evidence
- security/privacy 영향
- unresolved capability
- rollback
