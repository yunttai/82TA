---
name: service-ux-design
description: "Budget Route Platform의 장소·예산·출발시각 입력, 추천 카드, 지도, Bus Intelligence, P50/P90·비용 범위·provenance, COMPLETE/PARTIAL/오류 상태 UX와 접근성을 설계·검토한다. Service 화면·문구·상태·정보 구조 요청 시 사용한다."
---

# Service UX Design

확률·범위·fallback을 오인 없이 표현하는 사용자 경험을 정의한다.

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


## 기준

- `src/docs/harnesses/service-product/UX_INFORMATION_ARCHITECTURE.md`
- Public OpenAPI와 code registry
- capability와 partial semantics

## 워크플로우

1. 사용자 목표와 decision point를 식별한다.
2. 화면·상태·행동·오류를 state chart로 만든다.
3. 카드와 지도에 동일 route ID·leg sequence를 연결한다.
4. P50/P90, taxi expected/upper, freshness, data origin을 구분한다.
5. boardability를 보장처럼 쓰지 않는다.
6. warning code별 사용자 문구·행동·접근성 label을 정의한다.
7. keyboard, screen reader, contrast, reduced motion, mobile viewport를 검토한다.
8. Frontend와 QA에 acceptance를 전달한다.

## 출력

- 최종 UX 문서·component contract: `src/docs/harnesses/service-product/`
- 구현 대상: `src/apps/web/`
- 공통 code 의미 변경은 governance 요청
