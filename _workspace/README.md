# Harness Workspace

이 디렉터리는 하네스 실행 중 생성되는 **임시 분석·작업 조율 산출물**만 보관한다.

```text
_workspace/service-product/       Service Product Harness 실행 기록
_workspace/routing-intelligence/  Routing & Intelligence Harness 실행 기록
_workspace/integration/           두 작업흐름 통합·계약 QA 기록
```

최종 PRD, 설계 문서, 코드, 테스트, 인프라 파일은 반드시 `src/` 아래로 승격한다. `_workspace/` 파일을 제품의 원본으로 간주하지 않는다.
