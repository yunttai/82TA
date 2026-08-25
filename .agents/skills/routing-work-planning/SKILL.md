---
name: routing-work-planning
description: "공통 PRD를 Provider, entity mapping, route optimization, Bus Intelligence, data/model, private Django API, performance·security 작업으로 분해한다. Routing & Intelligence 기능 기획·백로그·작업 배정·부분 재실행 요청 시 사용한다."
---

# Routing Work Planning

Use this skill only when the user asks for planning, backlog decomposition, assignment, or a multi-component rerun. Do not insert a planning phase into a focused implementation request.

Start from current code and requested outcome. Split only work that can be independently accepted; do not manufacture tasks for every possible Routing layer.

## 분해 축

1. Provider capability·fixture·adapter
2. canonical transport model
3. route/stop/direction mapping
4. bounded candidate generation
5. time-dependent cost·budget·transfer
6. ETA·seat·expected wait·confidence
7. private API·cache·deadline
8. collector·data quality·model registry
9. replay·property·performance·security

각 task에는 최소한 outcome, affected path, dependency, acceptance check를 기록한다. Latency budget, failure behavior, fixture/test ID, contract, model/data version은 그 task에 실제로 관련될 때만 추가한다. `_workspace/WORKPLAN.md` 기록은 장기·위임 조율에 유용하거나 사용자가 요청했을 때만 한다.

## 금지

- 사용자 계정·저장 장소 task
- Frontend presentation JSON 설계
- raw Provider schema를 domain contract로 사용
- online request 중 training·heavy preprocessing
- 무제한 candidate/API call
- 구현 요청을 계획·audit·release verdict만으로 끝내기
