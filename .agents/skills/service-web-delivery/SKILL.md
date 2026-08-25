---
name: service-web-delivery
description: "React+TypeScript 모바일 우선 웹앱/PWA, Kakao Maps JS, generated Public API client, route search·recommendation·map·account UI를 계약 기반으로 구현·수정한다. Frontend 컴포넌트·페이지·hook·상태·PWA 작업 시 사용한다."
---

# Service Web Delivery

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


## 필수 입력

- Public OpenAPI generated TS client
- Public request/response examples
- UX information architecture
- reason/warning/error registry
- support capability

## 구현 원칙

- 수작업 API 타입과 `as any`로 계약을 우회하지 않는다.
- Routing API를 브라우저에서 직접 호출하지 않는다.
- 서버용 key를 bundle에 넣지 않는다.
- P50/P90·expected/upper·unknown/null을 보존한다.
- geometry가 없으면 정상 polyline으로 위장하지 않는다.
- URL route와 link를 교차 검증한다.
- semantic status별 화면과 retry 가능성을 구분한다.

## 워크플로우

1. OpenAPI client·fixture로 feature boundary를 만든다.
2. loading/complete/partial/empty/error/expired state를 먼저 구현한다.
3. search form과 validation을 구현한다.
4. recommendation cards와 leg detail을 구현한다.
5. Kakao map layer를 route data와 연결한다.
6. account/history/favorite/settings를 연결한다.
7. unit·component·contract·E2E·a11y test를 작성한다.
8. `service-incremental-qa`에 API↔hook↔UI 교차 검증을 요청한다.

## 출력

`src/apps/web/**`만 수정한다. 공통 field 필요 시 governance를 요청한다.
