# Repository and Contract Scripts

작업 범위에 맞는 검증 도구만 사용한다. local 구현 전에 전체 suite나 snapshot을 일괄 실행할 필요는 없다.

| 파일 | 목적 |
|---|---|
| `validate_repository.py` | `--layout-only`, `--harness-only`, 전체 검증 모드 |
| `validate_openapi.py` | OpenAPI YAML parse 및 repository-local `$ref` 존재 검증 |
| `validate_openapi_examples.py` | 네 개 canonical request/response 예제를 실제 JSON Schema에 대조 |
| `validate_harness_registry.py` | filesystem-backed agent/skill 설정 검증; locked v1 registry는 historical record |
| `validate_harness_evals.py` | 모든 active skill의 distinct positive/negative trigger matrix coverage 검증 |
| `verify_contract_lock.py` | 두 하네스가 읽는 공통 문서·계약의 SHA-256 drift 검사 |
| `update_contract_lock.py` | 승인된 공통 변경 후 lock 재생성 |
| `snapshot_context.py` | 선택적으로 단일 current snapshot 갱신; `--archive`일 때만 timestamp copy |
| `compare_context_snapshots.py` | 호환 이름을 유지하며 양쪽 live verified contract lock 직접 비교 |
| `create_contract_change_request.py` | 공통 계약 변경 요청 문서 생성 |
| `render_tree.py` | 현재 저장소 파일 목록 출력 |
| `generate_package_manifest.py` | `src/docs/PACKAGE_MANIFEST.md`를 현재 파일 목록으로 재생성 |

## 기본 실행

저장소 루트에서:

```bash
python -m pip install -r src/scripts/requirements-validation.txt
python src/scripts/validate_repository.py --harness-only
python src/scripts/validate_repository.py --layout-only

# 통합·릴리스 또는 전체 감사
python src/scripts/validate_repository.py
python src/scripts/compare_context_snapshots.py
```

`snapshot_context.py`는 명시적인 진단/감사 기록이 필요할 때만 실행한다. `update_contract_lock.py`는 task가 승인한 intentional canonical change와 관련 검증이 있을 때만 실행하며 drift를 감추는 데 쓰지 않는다.
