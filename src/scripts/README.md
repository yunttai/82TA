# Repository and Contract Scripts

모든 개발 하네스는 구현 전에 이 디렉터리의 검증 도구를 사용한다.

| 파일 | 목적 |
|---|---|
| `validate_repository.py` | 루트 배치 정책, 하네스 필수 파일, 문법, OpenAPI 예제, contract lock을 통합 검증 |
| `validate_openapi.py` | OpenAPI YAML parse 및 repository-local `$ref` 존재 검증 |
| `validate_openapi_examples.py` | 네 개 canonical request/response 예제를 실제 JSON Schema에 대조 |
| `validate_harness_registry.py` | 두 하네스의 오케스트레이터·에이전트·스킬·write scope를 단일 registry와 대조 |
| `verify_contract_lock.py` | 두 하네스가 읽는 공통 문서·계약의 SHA-256 drift 검사 |
| `update_contract_lock.py` | 승인된 공통 변경 후 lock 재생성 |
| `snapshot_context.py` | 실행 시점의 context/contract aggregate hash를 `_workspace/`에 고정 |
| `create_contract_change_request.py` | 공통 계약 변경 요청 문서 생성 |
| `render_tree.py` | 현재 저장소 파일 목록 출력 |
| `generate_package_manifest.py` | `src/docs/PACKAGE_MANIFEST.md`를 현재 파일 목록으로 재생성 |

## 기본 실행

저장소 루트에서:

```bash
python src/scripts/validate_repository.py
python src/scripts/snapshot_context.py service-product
python src/scripts/snapshot_context.py routing-intelligence
```

`update_contract_lock.py`는 공통 계약 변경에 대한 양쪽 검토가 끝난 뒤에만 실행한다.
