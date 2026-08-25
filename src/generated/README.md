# Generated Artifacts

Public Service OpenAPI 1.6.0과 Private Routing OpenAPI 1.2.0에서 생성한 consumer artifacts다. Private request의 `contractVersion: "1.0"`은 1.x wire compatibility family로 유지한다.

- `service-client-ts/`: Public Service API TypeScript schema와 `openapi-fetch` client
- `routing-client-python/`: Private Routing API Python models와 sync/async `httpx` client

재생성:

```bash
bash src/generated/generate-clients.sh
```

생성기는 먼저 contract lock을 검증하고, 외부 `$ref`를 임시 디렉터리에 bundle한 뒤 아래 고정 버전을 사용한다.

- `@redocly/cli@1.34.2`
- `openapi-typescript@7.9.1`
- `openapi-python-client==0.29.0`

`openapi-python-client`는 `date-time` header parameter를 생성하지 못한다. 따라서 생성용 Private API bundle에서만 `X-Request-Deadline`의 `format: date-time`을 제거한다. Canonical OpenAPI는 변경하지 않으며 generated client는 이 값을 계약에 맞는 timezone-aware ISO 8601 `str`로 받는다.

생성기·config·TypeScript/Python package source·lock file은 clean checkout에서 재생성할 수 있도록 commit 대상이다. `node_modules`, `.venv`, cache, `dist`, `build`는 commit하지 않는다.

추적된 생성물과 동일한지 검증:

```bash
bash src/generated/verify-reproducibility.sh
```
