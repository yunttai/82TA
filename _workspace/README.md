# Harness Workspace

이 디렉터리는 필요할 때만 쓰는 **임시·gitignored 분석 메모**다. 비어 있거나 오래되어도 정상이며, routine 작업의 사전 입력·현재 상태·완료 gate가 아니다.

```text
_workspace/service-product/       선택적 Service 작업 메모
_workspace/routing-intelligence/  선택적 Routing 작업 메모
_workspace/integration/           선택적 통합·계약 QA 메모
```

현재 상태는 소스·테스트·migration·active workflow와 live contract lock에서 확인한다. `snapshot_context.py`를 명시적으로 실행하면 기본적으로 `00_context_snapshot_current.json` 하나만 덮어쓴다. 장기 이력이 꼭 필요할 때만 `--archive`를 쓴다.

최종 제품 PRD, 설계 문서, 코드, 테스트, 인프라 파일은 `src/`에 둔다. `_workspace/` 파일을 제품 원본이나 승인 기록으로 간주하지 않는다.
