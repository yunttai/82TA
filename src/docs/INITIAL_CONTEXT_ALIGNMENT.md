# Initial Context Alignment Evidence

> **Historical archive (2026-08-22):** 아래 표는 초기 하네스 생성 시점의 1.0.0 snapshot 기록이며 현재 상태나 integration gate가 아니다. 현재 parity는 `python src/scripts/compare_context_snapshots.py`로 live verified contract lock을 직접 비교한다.

두 개발 하네스와 통합 검증 하네스가 동일한 canonical context에서 시작하는지 실제 snapshot으로 확인했다.

| Harness | Context Version | Contract Version | Aggregate SHA-256 |
|---|---|---|---|
| `service-product` | `1.0.0` | `1.0.0` | `35b94c0ba0c20b885db524b66f8c28bd62f1c8c034f9a084715c37c9b2429edf` |
| `routing-intelligence` | `1.0.0` | `1.0.0` | `35b94c0ba0c20b885db524b66f8c28bd62f1c8c034f9a084715c37c9b2429edf` |
| `integration` | `1.0.0` | `1.0.0` | `35b94c0ba0c20b885db524b66f8c28bd62f1c8c034f9a084715c37c9b2429edf` |

## 판정

- 동일 aggregate hash: `35b94c0ba0c20b885db524b66f8c28bd62f1c8c034f9a084715c37c9b2429edf`
- 결과: **PASS**
- 당시 snapshot은 동일했다. 현재는 snapshot 파일의 최신성을 가정하지 않고 각 작업tree의 live lock 검증과 직접 비교를 사용한다.
