# Branch / Worktree / Integration 운영

Branch와 worktree 구조는 팀 상황에 맞게 선택한다. 특정 branch 이름이나 세 개 worktree를 하네스가 강제하지 않는다.

## 독립 작업

- 같은 경계의 파일을 여러 branch/agent가 동시에 수정하지 않도록 실제 write scope를 나눈다.
- 작은 vertical slice를 자주 통합한다.
- 충돌 해결은 선언된 agent ownership이 아니라 current implementation, 사용자 의도, DB/context boundary, producer-consumer compatibility를 기준으로 한다.

## Shared contract

1. 변경된 의미와 실제 producer·consumer를 식별한다.
2. 영향을 받는 OpenAPI/client/test, DBML/migration, event/code만 고친다.
3. breaking/ownership/production platform 결정이면 CCR 또는 ADR과 migration/rollback을 추가한다.
4. affected tests 후 intentional canonical diff에 대해 lock을 갱신한다.
5. 통합 대상 양쪽의 live lock을 비교한다.

```bash
python src/scripts/compare_context_snapshots.py \
  --service-root <service-worktree> \
  --routing-root <routing-worktree>
```

기존 스크립트 이름은 호환성을 위해 남아 있지만 snapshot 파일을 읽지 않는다.

## Integration depth

- source merge: 변경된 경계의 targeted contract/integration checks
- environment deploy: live lock, generated client, representative replay/E2E, security/rollback
- release claim: 그 단계가 의존하는 provider/model/SLO/quota/DR evidence

disabled/unsupported/PARTIAL capability의 `UNVERIFIED`는 무관한 source merge를 막지 않는다.
