# 28. Provider 장애 대응

**사용 시점:** 실제 장애/쿼터 소진

```text
$provider-adapter-delivery
$integration-coherence-qa

[Provider/Capability] 장애를 진단하고 안전하게 대응해줘.

- auth/429/quota/timeout/5xx/schema/network를 분류한다.
- 키 값을 출력하지 않는다.
- circuit/cache/fallback/partial 영향을 확인한다.
- strict budget 또는 mapping/seat 정확성이 검증 불가하면 해당 후보/기능을 차단한다.
- 사용자 warning/status와 운영 alert/runbook을 갱신한다.
- 정상화 후 canary/probe와 regression fixture를 추가한다.
- incident timeline, 영향, 임시조치, 근본원인, 재발방지를 작성한다.
```
