# 08. 외부 Provider 연동

**사용 시점:** 신규 API/응답 변경/키 검증

```text
$provider-adapter-delivery

다음 Provider capability를 검증하고 Adapter를 구현 또는 수정해줘.

Provider/Capability: [예: Kakao Mobility MULTI_DESTINATION]

- 공식 문서와 현재 key 실제 호출 가능성을 구분한다.
- 키 값을 출력/기록하지 않는다.
- DOCUMENTED→KEY_VERIFIED→PRODUCTION_APPROVED 상태를 각각 판정한다.
- endpoint allowlist, request/response schema, null/0, 좌표/시간/단위, timeout/retry/circuit/quota/cache/retention을 정의한다.
- 정상/빈결과/timeout/429/5xx/schema drift/stale fixture를 만든다.
- raw shape를 canonical domain에 누출하지 않는다.
- 미승인 기능이면 capability false와 fallback을 유지한다.
- tests와 capability matrix/STATUS/HANDOFF를 갱신한다.
```
