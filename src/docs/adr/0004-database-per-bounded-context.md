# ADR-0004: Database per Bounded Context

## 상태
Accepted

## 결정
Service DB와 Routing DB를 논리 분리하고 cross-query·cross-FK·ORM 공유를 금지한다.

## 결과
필요 데이터는 API 또는 비식별 event로 전달한다. 같은 RDS를 초기 공유해도 role/database를 분리한다.
