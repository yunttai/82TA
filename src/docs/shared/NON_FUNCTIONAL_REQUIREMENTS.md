# Non-Functional Requirements

## 성능

| ID | 요구사항 |
|---|---|
| NFR-PERF-001 | Public route search P95 7초 이하 목표 |
| NFR-PERF-002 | Routing hard deadline 6.5초 이하 |
| NFR-PERF-003 | model batch inference 300ms 내 목표 |
| NFR-PERF-004 | candidate count를 설정 상한으로 제한 |
| NFR-PERF-005 | 동일 요청 single-flight와 cache 사용 |

## 신뢰성

| ID | 요구사항 |
|---|---|
| NFR-REL-001 | Provider 부분 장애 시 PARTIAL 결과 |
| NFR-REL-002 | timeout·retry·circuit breaker·stale policy |
| NFR-REL-003 | deterministic replay |
| NFR-REL-004 | RDS PITR와 정기 restore drill |
| NFR-REL-005 | model rollback 15분 이내 목표 |

## 데이터·모델

| ID | 요구사항 |
|---|---|
| NFR-DATA-001 | observed/ingested/valid time 분리 |
| NFR-DATA-002 | future target 결측을 negative로 사용 금지 |
| NFR-DATA-003 | temporal·trip group split |
| NFR-DATA-004 | feature schema version과 train/serve parity |
| NFR-DATA-005 | probability calibration과 coverage 공개 |
| NFR-DATA-006 | schema drift 탐지와 잘못된 0값 생성 금지 |

## 보안·개인정보

| ID | 요구사항 |
|---|---|
| NFR-SEC-001 | 서버 key를 browser에 노출하지 않음 |
| NFR-SEC-002 | private Routing API와 service authentication |
| NFR-SEC-003 | 정확한 위치·번호판·token 로그 금지 |
| NFR-SEC-004 | model registry·hash·schema 검증 |
| NFR-SEC-005 | WAF·rate limit·Denial of Wallet 대응 |
| NFR-SEC-006 | 사용자 삭제·export·동의 기록 |

## 계약·유지보수

| ID | 요구사항 |
|---|---|
| NFR-CONTRACT-001 | OpenAPI·DBML·code registry 단일 원본 |
| NFR-CONTRACT-002 | 두 하네스 context hash lock |
| NFR-CONTRACT-003 | generated client 사용 |
| NFR-MAINT-001 | Routing domain Django 독립 |
| NFR-MAINT-002 | Provider Adapter와 canonical model |
| NFR-MAINT-003 | 모든 제품 산출물 `src/` 하위 |

## Observability

- correlation ID
- endpoint/status/latency
- provider operation/status/cache/quota
- candidate generated/pruned/evaluated/Pareto count
- model version·mapping version·ranking policy
- data freshness·coverage·warning code
- 정확한 좌표와 user identity는 제외
