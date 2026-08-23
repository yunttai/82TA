# Decision and Change Control

## 1. 단일 원본

공통 목표·용어·API·ERD·오류 코드·서비스 경계는 다음 경로만 원본이다.

```text
src/docs/shared/
src/contracts/
```

각 하네스 문서는 원본을 링크하고 workstream 해석·작업·수용기준만 추가한다. 공통 스키마를 복사하여 수정하지 않는다.

## 2. 변경 유형

| 유형 | 예 | 요구 절차 |
|---|---|---|
| 설명 보완 | 의미를 바꾸지 않는 문구 | 문서 PR + QA |
| 호환 추가 | optional field, endpoint 추가 | contract minor + 예제·client·tests |
| 의미 변경 | field 의미·단위·null 정책 | ADR + major 또는 adapter |
| DB 변경 | column·constraint·ownership | DBML + migration plan + producer/consumer |
| 경계 변경 | Provider 조율을 Service로 이동 등 | ADR + architecture audit + 양쪽 승인 |
| 보안·개인정보 | 위치 보존·인증·로그 | threat model + security approval |

## 3. 원자적 변경 세트

계약 변경은 필요에 따라 다음을 하나의 change set으로 갱신한다.

1. ADR
2. 공통 PRD·용어
3. OpenAPI·DBML·event·code registry
4. request/response examples
5. generated client 또는 생성 규칙
6. requirements traceability
7. consumer/provider contract tests
8. changelog와 version
9. `CONTRACT_LOCK.json`

일부만 바뀐 상태는 merge하지 않는다.

## 4. 두 하네스의 행동

- 변경이 필요하다고 발견한 하네스는 구현을 임의 확장하지 않고 `_workspace/integration/contract-change-request.md`를 만든다.
- `shared-contract-governance`가 변경 범위와 호환성을 판정한다.
- Service와 Routing QA가 각각 생산자·소비자 관점에서 승인한다.
- lock 갱신 뒤 각 하네스는 새 context snapshot을 만든다.

## 5. Drift 판정

다음 중 하나라도 발생하면 drift다.

- 동일 개념의 수작업 DTO·enum·ERD 복사본
- OpenAPI와 실제 serializer 응답 불일치
- DBML과 ORM/migration의 null·constraint·ownership 불일치
- code registry에 없는 UI 문구 분기
- manifest hash 불일치
- Service가 Routing 수치를 재계산
- Routing이 사용자 identity를 저장

Drift가 있는 동안 통합·릴리스는 차단한다.
