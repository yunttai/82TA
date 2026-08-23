# CI/CD Requirements

PR:

- source layout/contract lock
- lint/type/unit/property
- OpenAPI/DBML/examples
- consumer/provider contract
- migration checks
- fixture replay
- frontend build/accessibility
- SAST/dependency/container/IaC scan
- SBOM

Main:

- build immutable artifacts/images
- dev deploy + smoke
- staging integration/performance
- production approval/release tag
- rolling or blue/green
- code/model/database rollback

GitHub workflow 실파일도 제품 산출물로 `src/infra/ci/github-actions/`에 관리하고, 저장소 활성화 단계에서 root `.github/workflows` 배치 여부를 별도 ADR로 결정한다.
