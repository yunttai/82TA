# Django Routing & Intelligence API

비공개 `POST /v1/routes/optimize` 경계, Provider orchestration, 후보 생성,
Bus Intelligence enrichment, Pareto·ranking을 제공한다. 사용자 계정 데이터를
받거나 저장하지 않는다.

HTTP 경계는 canonical OpenAPI 요청을 검증한 뒤 좁은 routing use-case port에
위임한다. 운영 default backend는 fail-closed `503`을 반환한다. 명시적 local
fixture scenario 또는 DI만 Provider→canonical→mapping→Bus Intelligence→optimizer
composition을 활성화한다. Local fixture scenario는 아래의 opt-in과 non-production
runtime gate를 함께 통과해야 한다. 미검증 live Provider 기능은 모두 disabled이고
fixture fallback 응답은 `PARTIAL`이다.

## Local test

```powershell
python -m pip install -r src/services/routing-api/requirements.txt
$env:PYTHONPATH = (Resolve-Path 'src/services/routing-api').Path
python -B -m pytest src/services/routing-api/routing_api/tests -q -p no:cacheprovider
```

운영 기동 시 `ROUTING_SERVICE_JWT_SECRET`을 설정한다. bearer는 구성된 issuer와
audience, expiry, non-empty string `jti`를 검증하는 HS256 service JWT다. liveness만
인증 없이 제공한다. 일회성 `jti` 소비/replay cache는 현재 계약에 없으므로 이
서비스가 임의로 추가하지 않는다.

## Explicit fixture mode

Fixture composition은 세 설정이 모두 유효해야만 켜진다:

```powershell
$env:ROUTING_RUNTIME_ENVIRONMENT = 'DEVELOPMENT' # 또는 TEST
$env:ROUTING_ALLOW_FIXTURE_BACKEND = 'true'      # default false
$env:ROUTING_FIXTURE_SCENARIO = 'R1'             # closed allowlist
```

`ROUTING_FIXTURE_SCENARIO`만 설정됐거나 runtime이 `PRODUCTION`/`STAGING`이면
backend는 `fixture-blocked` fail-closed 상태이며 fixture route를 반환하지 않는다.
scenario는 API request로 선택할 수 없다.
성공 scenario는 RI-200 sanitized typed fixtures와 canonical values만으로 COARSE
strategy를 만들고, 후보별 exactification dependency DAG를 선행 leg P50 종료시각에
따라 해결한다. 같은 depth의 독립 호출만 bounded fan-out하고 WALK/TRANSIT은 전파된
entry time, TAXI directions는 별도 dispatch P50 이후 시각을 사용한다. 그 결과로
immutable EXACT input을 재생성한 다음 time-dependent optimizer가 chronology,
transfer, strict Taxi upper budget, Pareto와 네 recommendation을 다시 검증한다.
생성 대상은 canonical 7 pattern이며 사용자 결과는 domain의 V1 result cap을 따른다.
fixture 성공은 live capability나 deployed model readiness를 승격하지 않는다.
checkout 전용 `routing_api.workspace_packages.activate_workspace_packages()`가 세
internal package root를 명시적으로 활성화한다. fixture integration은 설치된
internal package를 먼저 import하고, 누락된 명시적 checkout 실행에서만 activator를
호출한다. fail-closed 운영 default는 activator를 호출하지 않으며, 배포는 반드시
설치된 internal wheel을 사용한다. 이 경로는 live fallback 또는 운영 Provider
대체물이 아니다.

## Packaging and production blockers

- Routing API 자체 runtime dependency와 wheel metadata는 `pyproject.toml`에 있다.
- Production DI는 exact Provider-operation transport/credential binding과 하나의
  coherent capability registry를 요구한다. Registry approval만으로는 부족하며
  endpoint/auth, verified schema/version, unexpired runtime evidence가 모두 통과한
  operation만 실행 및 `/capabilities` projection 대상이다. 현재 operation은 전부
  false/`DISABLED`이고 cached default는 zero-call `503`이다.
- Routing API wheel에는 runtime `routing_api`와 sibling `transport_mapping` package가
  함께 들어가며 두 package의 test package는 배포 wheel에서 제외한다.
- 세 internal package는 PEP 517 metadata와 editable/wheel import evidence가 있다.
  배포 image는 Python `>=3.12`에서 이 internal wheel들과 Routing API의
  `integration` extra를 설치해야 한다. 저장소 밖 임시 venv에서 네 non-editable
  wheel만 설치한 import 및 R1 integrated fixture smoke는 통과했지만 실제 image와
  reproducibility evidence가 나오기 전에는 integrated production mode를 승인하지
  않는다.
- OpenAPI의 `/internal/admin/**` operation은 operator role/environment claim,
  namespace allowlist, artifact digest/lifecycle와 immutable audit service를 통해서만
  실행된다. URL은 등록되어 있지만 default container는 durable audit와 approved
  registry를 임의 구성하지 않으므로 404 fail-closed다. 배포 composition이 이
  dependency를 명시적으로 주입해야 한다.
- Routing DB는 `OptimizationResultRepository` 경계를 통해 request fingerprint와
  candidate/leg/provenance만 저장한다. raw provider payload, secret, Service DB 또는
  user identity는 port에 존재하지 않는다. persistence 미주입/실패는 응답의
  `computation.cache.optimizationPersistence`에 명시된다. BUS enrichment의 mapping
  UUID와 ETA/Seat model version은 matching leg evaluation에서만 가져오며 요청 전체
  aggregate를 각 leg에 재사용하지 않는다.
- process-local admission/idempotency는 단일 process foundation이다. 운영 ingress
  rate limit, shared idempotency/single-flight, load shedding evidence가 별도로 필요하다.
