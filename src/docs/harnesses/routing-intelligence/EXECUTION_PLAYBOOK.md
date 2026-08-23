# Routing & Intelligence Harness Execution Playbook

## 시작

```bash
python src/scripts/validate_repository.py
python src/scripts/snapshot_context.py routing-intelligence
```

## Phase 팀

1. Provider·Mapping 팀
2. Bus Intelligence·Optimization·Data/ML 팀
3. API·Security·Performance·QA 팀

각 팀은 primary thread plan→named subagent delegation→durable WORKPLAN/STATUS/HANDOFF→incremental QA→subagent result collection 수명주기를 따른다.

## 표준 흐름

1. Provider capability와 fixtures
2. canonical normalization
3. route/stop/direction mapping과 gold set
4. trip/label/feature data
5. ETA·Seat·expected wait
6. bounded candidate·time-dependent cost·strict budget
7. Pareto/ranking/reason
8. private API/deadline/partial
9. deterministic replay·load·security
10. Service generated client integration

## 완료 보고 형식

- Requirement IDs
- Provider capability state
- context/contract/model/mapping/ranking versions
- 변경 파일
- candidate/API call/latency evidence
- model/data/replay evidence
- partial/fallback behavior
- security/cost/rollback
