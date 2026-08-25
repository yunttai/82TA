# 16. Reason/Warning/Error 코드 변경

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** 사용자 설명/오류 코드 변경

```text
$shared-contract-governance

다음 Reason/Warning/Error code 변경을 제안 또는 적용해줘: [변경].

- reason, warning, error를 정확히 분류한다.
- 기존 의미와 중복/충돌을 검사한다.
- canonical registry, OpenAPI examples, domain producer, Service projection, UI localization/renderer, tests를 함께 맞춘다.
- consumer의 unknown-code fallback을 검증한다.
- 제거/의미변경이면 breaking/deprecation을 적용한다.
```
