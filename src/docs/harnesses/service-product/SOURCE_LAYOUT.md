# Service Product Source Layout

## 최종 쓰기 범위

```text
src/apps/web/
src/services/service-api/
src/docs/harnesses/service-product/
src/tests/contracts/
src/tests/integration/
src/tests/e2e/
src/tests/security/
```

## React Web/PWA 권장 내부 구조

```text
src/apps/web/
├─ package.json
├─ tsconfig.json
├─ vite.config.* 또는 동등한 React build 설정
├─ public/
└─ src/
   ├─ app/                    bootstrap, router, providers
   ├─ pages/                  URL 화면
   ├─ features/
   │  ├─ place-search/
   │  ├─ route-search/
   │  ├─ route-results/
   │  ├─ route-map/
   │  ├─ account/
   │  ├─ history/
   │  ├─ favorites/
   │  └─ preferences/
   ├─ entities/               generated API model을 표시용으로 조합
   ├─ shared/
   │  ├─ api/                 generated client wrapper
   │  ├─ ui/
   │  ├─ map/
   │  ├─ telemetry/
   │  └─ test/
   └─ service-worker/
```

수작업 OpenAPI DTO를 `entities`에 복사하지 않는다. generated client type을 원본으로 사용하고 표시 전용 view model만 만든다.

## Django Service API 권장 내부 구조

```text
src/services/service-api/
├─ manage.py
├─ pyproject.toml
├─ config/                    settings, URLs, ASGI/WSGI
├─ identity/
├─ preferences/
├─ places/
├─ journeys/
├─ favorites/
├─ consent/
├─ operations/
├─ routing_client/            generated client + Gateway adapters
└─ tests/
```

각 app은 API/ application/ domain/ infrastructure 관심사를 코드 규모에 맞게 분리한다. Routing DB model이나 Provider adapter를 이 서비스에 만들지 않는다.

## 금지

- 루트 또는 `src/services/routing-api`에 Service 제품 코드 작성
- Frontend에서 private Routing URL 호출
- Public API schema 수작업 복사
- Service에서 route time·cost·rank 재계산
