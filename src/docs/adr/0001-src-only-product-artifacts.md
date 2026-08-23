# ADR-0001: 모든 제품 산출물을 `src/` 아래에 둔다

## 상태
Accepted

## 결정
`.codex`, `.agents`, `_workspace`, `AGENTS.md`, root README·git metadata를 제외한 코드·문서·계약·테스트·인프라를 `src/`에 둔다.

## 이유
하네스 제어면과 제품 원본을 분리하고 두 작업흐름의 경로 충돌을 방지한다.

## 결과
root allowlist 검증을 CI와 하네스 시작·종료 시 실행한다.
