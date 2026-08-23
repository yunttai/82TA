---
name: service-web-delivery
description: "React+TypeScript 모바일 우선 웹앱/PWA, Kakao Maps JS, generated Public API client, route search·recommendation·map·account UI를 계약 기반으로 구현·수정한다. Frontend 컴포넌트·페이지·hook·상태·PWA 작업 시 사용한다."
---

# Service Web Delivery

## 공통 사전 조건

작업을 시작하기 전에 반드시 다음을 수행한다.

1. `python src/scripts/validate_repository.py`를 실행한다.
2. `python src/scripts/verify_contract_lock.py`를 실행한다.
3. `src/contracts/CONTEXT_MANIFEST.json`과 `src/contracts/CONTRACT_LOCK.json`을 읽는다.
4. `src/docs/shared/PROJECT_CONTEXT.md`, `PRD.md`, 관련 canonical 계약을 읽는다.
5. 이전 `_workspace/` 산출물이 있으면 미완료·피드백·차단 사항을 확인한다.

검증 실패 시 구현을 진행하지 않는다. 공통 원본을 임의로 맞춰 쓰지 말고 drift 또는 change request로 처리한다.

## 저장 위치 규칙

- 분석·토론·중간 결과: `_workspace/{workstream}/`
- 검토가 끝난 제품 코드·문서·테스트·인프라: 반드시 `src/` 아래
- 루트에는 `.codex/`, `.agents/`, `_workspace/`, `src/`, `AGENTS.md`, `README.md`, `.gitignore`만 둔다.
- 공통 PRD·OpenAPI·ERD·enum 복사본을 workstream 폴더에 만들지 않는다.


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
