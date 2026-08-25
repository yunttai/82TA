---
name: service-security-review
description: "React와 Django Public Service의 session·cookie·CSRF·CORS·CSP·XSS·IDOR, 위치·저장 장소, rate limit·Denial of Wallet, 로그·관리자·dependency 보안을 위협모델과 테스트로 검토한다. Service 기능 완료·PR·릴리스 전 사용한다."
---

# Service Security Review

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

Focused change에서는 새로 생기거나 수정된 trust·privacy·abuse 경계만 검토한다. Redis coordination만 바뀌었다면 process 간 상태 공유와 fail-open/fail-closed 동작을 확인하되, 응답 캐싱을 실제로 추가하지 않는 한 Provider 약관, cache TTL, 좌표·검색어 key 비식별화, 외부 API 호출 정책까지 범위를 확장하지 않는다. 그 인접 항목은 현재 변경의 blocker가 아니다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


## 우선 검토

- browser↔Public API trust boundary
- guest token과 사용자 object ownership
- secure/HttpOnly/SameSite cookie, CSRF
- Kakao JS key domain restriction와 server key 비노출
- exact coordinate·saved label·email log redaction
- WAF/rate limit/idempotency/cache abuse
- result HTML/Provider text XSS
- admin·support·delete/export authorization

## 절차

변경 범위에 해당하는 절차만 수행한다. 전체 threat model, dependency/SAST/IaC, release 판정은 명시적 광범위 보안·배포·릴리스 요청에만 요구한다.

1. data flow와 threat model 변경 확인
2. abuse cases와 security acceptance 정의
3. 코드·configuration·tests를 양쪽에서 확인
4. secret/dependency/SAST/IaC evidence 확인
5. finding을 severity·exploitability·affected data·fix·retest로 기록
6. Critical/High는 release를 차단한다.

## 출력

`src/tests/security/` evidence와 관련 threat model/runbook. 공통 privacy 의미 변경은 governance로 보낸다.
