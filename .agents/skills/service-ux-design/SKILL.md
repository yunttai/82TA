---
name: service-ux-design
description: "Budget Route Platform의 장소·예산·출발시각 입력, 추천 카드, 지도, Bus Intelligence, P50/P90·비용 범위·provenance, COMPLETE/PARTIAL/오류 상태 UX와 접근성을 설계·검토한다. Service 화면·문구·상태·정보 구조 요청 시 사용한다."
---

# Service UX Design

확률·범위·fallback을 오인 없이 표현하는 사용자 경험을 정의한다.

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
