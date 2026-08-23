# ADR-0002: 두 하네스는 하나의 공통 계약 원본을 사용한다

## 상태
Accepted

## 결정
Service Product와 Routing & Intelligence는 `src/docs/shared`와 `src/contracts`를 공동 원본으로 읽는다. workstream별 API·ERD·DTO 복사본을 금지한다.

## 결과
contract manifest/hash, joint approval, consumer/provider QA가 필수다.
