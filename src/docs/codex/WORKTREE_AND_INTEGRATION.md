# Branch / Worktree / Integration 운영

## 권장 브랜치

```text
main
workstream/service-product
workstream/routing-intelligence
integration/current
contract/<change-name>
```

## 권장 worktree

```bash
git worktree add ../budget-route-service -b workstream/service-product
git worktree add ../budget-route-routing -b workstream/routing-intelligence
git worktree add ../budget-route-integration -b integration/current
```

## 공통 계약

한 작업흐름이 공통 계약을 직접 확정하지 않는다.

1. `13_CONTRACT_CHANGE_PROPOSAL.md`
2. 사용자/두 담당자 승인
3. contract branch에서 `14_APPLY_APPROVED_CONTRACT_CHANGE.md`
4. 양쪽 브랜치에 contract commit을 먼저 반영
5. 생성 client와 consumer/provider tests
6. lock/snapshot parity
7. 기능 구현 재개

## 최초 통합

- 양쪽 HANDOFF
- context sync
- integration branch에서 Service consumer와 Routing producer 연결
- mock↔real parity
- R1~R4
- security/performance
- merge readiness

## 반복 통합

작은 vertical slice마다 통합한다. 마지막에 대규모 병합하지 않는다.

## 충돌

- 제품 의미 충돌: PRD/ADR/contract governance
- 파일 충돌: ownership 기준
- DB 충돌: context별 migration 소유권
- generated client 충돌: 계약 원본에서 재생성
- 결과 차이: deterministic replay와 ranking version 비교
