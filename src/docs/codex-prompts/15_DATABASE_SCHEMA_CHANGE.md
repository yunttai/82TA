# 15. DB 스키마/Migration 변경

**사용 시점:** Service 또는 Routing DB 변경

```text
$shared-contract-governance

다음 DB 변경을 설계·적용해줘: [변경].

- 어느 bounded context 소유인지 먼저 확정한다.
- DBML/ERD/data ownership/data retention을 갱신한다.
- Django migration, backfill, index/lock/query impact, expand-contract 순서, rollback/forward-fix를 설계한다.
- 상대 DB foreign key/direct query를 만들지 않는다.
- API/event 영향이 있으면 같은 change set에 포함한다.
- migration tests와 staging rehearsal를 작성한다.
- 승인 없는 contract lock 갱신 금지.
```
