# 30. 배포·모델·계약 롤백

**사용 시점:** 통합/배포 후 문제

```text
문제를 더 확산시키지 말고 다음 rollback을 계획·실행해줘: [서비스/모델/계약/DB].

- 현재 영향과 last known good version을 확인한다.
- 데이터 손실 가능성과 backward compatibility를 평가한다.
- application/image/feature flag/model registry/cache/migration 각각의 rollback 가능성을 구분한다.
- destructive DB rollback 대신 forward fix가 안전한지 판단한다.
- contract consumer/producer overlap을 확인한다.
- smoke/replay/security와 context/lock을 재검증한다.
- incident와 재진입 조건을 기록한다.
```
