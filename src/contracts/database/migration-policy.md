# Database Migration Policy

- 각 DB migration은 소유 하네스가 작성하고 상대 DB를 변경하지 않는다.
- 공통 API 의미에 영향을 주는 schema 변경은 ADR와 contract change가 먼저다.
- production은 expand/contract migration을 사용한다.
- destructive change를 코드 전환과 같은 배포에서 수행하지 않는다.
- large table backfill·index는 별도 job과 lock 영향 분석이 필요하다.
- rollback 또는 forward-fix 전략을 PR에 명시한다.
- DBML과 Django migration/model의 교차 검증을 CI에서 수행한다.
- exact coordinate·sensitive label column 추가는 privacy review가 필수다.
