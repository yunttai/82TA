# Initial Context Alignment Evidence

두 개발 하네스와 통합 검증 하네스가 동일한 canonical context에서 시작하는지 실제 snapshot으로 확인했다.

| Harness | Context Version | Contract Version | Aggregate SHA-256 |
|---|---|---|---|
| `service-product` | `1.0.0` | `1.0.0` | `35b94c0ba0c20b885db524b66f8c28bd62f1c8c034f9a084715c37c9b2429edf` |
| `routing-intelligence` | `1.0.0` | `1.0.0` | `35b94c0ba0c20b885db524b66f8c28bd62f1c8c034f9a084715c37c9b2429edf` |
| `integration` | `1.0.0` | `1.0.0` | `35b94c0ba0c20b885db524b66f8c28bd62f1c8c034f9a084715c37c9b2429edf` |

## 판정

- 동일 aggregate hash: `35b94c0ba0c20b885db524b66f8c28bd62f1c8c034f9a084715c37c9b2429edf`
- 결과: **PASS**
- 이후 어느 하네스든 공통 파일을 단독 수정하면 `verify_contract_lock.py`와 snapshot 비교가 실패한다.
