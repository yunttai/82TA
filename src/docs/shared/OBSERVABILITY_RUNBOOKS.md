# Observability and Runbook Requirements

## SLO 제안

| 항목 | 목표 |
|---|---|
| Public availability | 99.9% |
| Search P50 | 3.5초 이하 |
| Search P95 | 7초 이하 |
| Search P99 | 10초 이하 또는 PARTIAL |
| strict budget violation | 0건 목표 |
| stale 실시간 오표시 | 0건 |
| model rollback | 15분 이내 |

## 핵심 Metric

### Service

- search success/error/latency
- guest/auth ratio
- public cache hit
- rate limit
- recommendation selected
- favorite/feedback conversion

### Routing

- Provider latency/error/timeout/quota
- candidate generated/pruned/evaluated/Pareto
- COMPLETE/PARTIAL ratio
- budget rejection
- mapping grade·coverage
- model inference latency
- replay mismatch

### Data/Model

- collector lag·duplicate·missing
- route/stop/trip/label coverage
- positive rate drift
- schema drift
- prediction distribution·missing feature
- shadow disagreement

## Runbook 목록

1. Public API 장애
2. Routing deadline 초과
3. Kakao 429·quota 소진
4. GBIS stale·schema drift
5. Routing DB/Redis 장애
6. Collector lag·duplicate
7. Model load 실패·rollback
8. Mapping 긴급 비활성화
9. Key 유출·rotation
10. 비용 급증·Denial of Wallet
11. 사용자 데이터 삭제 실패
12. RDS restore
13. Production deploy rollback
