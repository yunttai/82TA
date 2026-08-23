# 17. 두 작업흐름 Context 동기화

**사용 시점:** 따로 작업한 후 통합 전

```text
$shared-context-loader
$integration-coherence-qa

Service Product와 Routing & Intelligence의 context를 동기화해줘. 제품 코드는 수정하지 마라.

1. repository/lock을 검증한다.
2. 두 WORKPLAN/STATUS/HANDOFF와 branch diff를 읽는다.
3. 두 snapshot을 새로 생성하고 compare_context_snapshots.py를 실행한다.
4. contextVersion, contractVersion, aggregate hash, canonical file hashes, generated client version을 비교한다.
5. drift가 있으면 어느 branch가 어떤 canonical 파일을 변경했는지 분류한다.
6. 승인된 change인지 확인하고, 아니라면 lock 갱신/병합을 금지한다.
7. 통합 가능 여부와 필요한 선행 작업을 _workspace/integration에 기록한다.
```
