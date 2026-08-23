# 04. 1번 버그 수정

**사용 시점:** React/Django Service 결함

```text
Service Product의 다음 버그를 수정해줘.

버그: [증상/재현/기대]

1. AGENTS.md와 계약을 읽는다.
2. service-qa-engineer 또는 service-ux-engineer에 재현과 소유 경로 파악을 위임한다.
3. 원인 확정 후 frontend/backend owner에게 최소 수정과 회귀 test를 위임한다.
4. Routing/contract 원인이면 cast·임시 필드·재계산으로 숨기지 말고 integration finding을 작성한다.
5. 테스트와 validation을 실행하고 STATUS에 원인/재발방지를 기록한다.

관련 없는 파일을 수정하지 마라. 실제 원인, 수정, 회귀 테스트, 계약 영향, 남은 위험을 보고하라.
```
