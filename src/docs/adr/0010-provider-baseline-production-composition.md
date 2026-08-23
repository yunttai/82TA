# ADR-0010: 실Provider baseline과 선택적 Bus Intelligence를 분리한다

- 상태: Accepted
- 날짜: 2026-08-24
- 결정자: Product owner, Service Product owner, Routing & Intelligence owner
- 관련 요구사항: UJ-004, FR-ROUTE-001..005, FR-BUS-001..009,
  FR-OPS-001, BR-003, BR-005, BR-009, BR-010
- 관련 계약: `src/contracts/openapi/routing-private.v1.yaml`,
  `src/contracts/openapi/service-public.v1.yaml`,
  `src/contracts/codes/reason-warning-error-codes.yaml`

## Context

Internal Alpha의 목표는 실제 Provider로 transit/taxi baseline을 만들고 Service에서
소비하는 것이다. 기존 production composition은 실행 가능한 transit Provider뿐
아니라 PostGIS mapping, Routing persistence, ACTIVE ETA predictor와 ACTIVE Seat Risk
predictor가 모두 있어야만 시작했다. 이 조건은 Model Alpha에는 안전하지만,
GBIS 좌석 데이터가 없어도 transit/taxi 경로를 `PARTIAL`로 반환하라는 UJ-004와
Internal Alpha의 단계 순서를 막는다.

동시에 key 존재만으로 Provider를 활성화하거나, 모델이 없는데 확률·버전을
만들거나, production에서 fixture backend로 후퇴하면 안 된다. Service는 계속
HTTP `RoutingGateway`만 사용하고 Routing의 순위·시간·비용을 재계산하지 않는다.

## Decision

1. Production composition을 두 층으로 나눈다.
   - **필수 baseline:** 공식 raw schema를 canonical itinerary로 정규화하는 transit
     Provider와, 해당 operation의 documentation/key/schema/production approval/runtime
     evidence, operation-scoped credential/transport, strict optimizer, Routing-owned
     persistence.
   - **선택 enrichment:** PostGIS mapping, GBIS observations, ETA predictor, Seat Risk
     predictor, KMA/GITS context와 Taxi dispatch model.
2. 필수 baseline이 검증됐으면 선택 enrichment가 전부 없는 원자적 상태를 허용한다.
   mapping/model 일부만 임의로 주입된 혼합 상태는 거부한다.
3. BUS leg가 실제로 포함된 결과에서 mapping이 없거나 gate를 통과하지 못하면
   `PARTIAL`, `busIntelligence=null`, `mappingVersion=null`, `modelVersions=[]`와
   `BUS_MAPPING_LOW_CONFIDENCE`를 반환한다. HIGH mapping 뒤 GBIS/model evidence가
   없으면 `BUS_DATA_UNAVAILABLE`을 사용한다. 없음은 낮은 위험이나 numeric zero가
   아니다.
4. BUS leg가 없는 subway/train/taxi/walk 결과는 Bus enrichment 부재만으로
   `PARTIAL`이 되지 않는다. 실제 사용한 Provider와 enrichment의 완전성으로 상태를
   결정한다.
5. capability와 readiness는 분리한다. 실행 가능한 baseline operation만 true가 될
   수 있고, active attested model이 없으면 `busEtaModel=false`,
   `busSeatRisk=false`, models는 빈 배열이며 readiness는 degraded일 수 있다.
6. composition root는 ordinary `routing_api`와 분리된 packaged
   `routing_deployment` 모듈에 둔다. 이 모듈이 Django WSGI application 생성 전에
   exact `ProductionCompositionDependencies`를 한 번 등록한다. `routing_api`와 pure
   domain은 배포 모듈을 역으로 import하지 않는다.
7. Service production은 HTTPS `HttpRoutingGateway`만 사용한다. stub/replay backend는
   development/test에만 남고 production에서 자동 fallback하지 않는다.
8. Provider key 값, raw payload와 evidence 원문은 source, fixture, response, 일반
   로그에 넣지 않는다. key 존재는 capability 또는 production approval을 자동
   승격하지 않는다.

## Alternatives Considered

1. **모든 Bus model과 PostGIS가 준비될 때까지 route 전체를 503으로 둔다.**
   UJ-004와 Internal Alpha를 막고, 이미 검증된 transit/taxi baseline을 버리므로
   거부한다.
2. **key가 있으면 development/staging에서 capability를 자동 활성화한다.**
   schema drift, 상용 승인, quota와 egress 통제를 우회하므로 거부한다.
3. **production에서 fixture backend로 자동 fallback한다.** 실제 Provider 장애를
   성공처럼 숨기고 provenance를 오염시키므로 거부한다.
4. **Service가 Provider를 직접 호출하거나 Bus 값을 보정한다.** bounded context와
   DB/secret 소유권을 깨므로 거부한다.

## Consequences

- 실제 Provider와 strict optimizer를 먼저 E2E로 검증할 수 있고, Model Alpha는 같은
  private API 뒤에서 점진 활성화할 수 있다.
- BUS 결과는 enrichment 부재를 명시적으로 노출하지만 다른 mode의 완전한 결과를
  불필요하게 degrade하지 않는다.
- deployment factory/evidence bundle, Routing DB migration, private network와
  egress-control attestation이 운영 필수 산출물이 된다.
- `PARTIAL`과 capability false가 늘 수 있으므로 Service UI와 telemetry는 이를 정상
  상태로 처리해야 한다.

## Security / Privacy / Cost

Provider endpoint는 exact HTTPS allowlist이며 credential은 operation scope에 묶는다.
Runtime execution은 key verification, response schema version, production approval와
유효기간이 있는 evidence를 모두 요구한다. 외부 proxy/firewall attestation이 없는
직접 egress는 fail closed한다. Provider call cap, timeout, retry, semaphore,
single-flight, 6.5초 Routing deadline과 Service의 500ms network margin을 유지한다.
Service identity와 사용자 저장 장소·계정 정보는 Routing request에 들어가지 않는다.

## Migration and Rollback

1. raw adapter와 evidence loader를 disabled-by-default로 배포한다.
2. `routing_deployment` WSGI와 baseline factory를 배포하되 evidence/key가 없으면
   unavailable/all-false 상태를 유지한다.
3. private Routing과 Service HTTP gateway를 연결하고 production-shaped E2E를 통과한다.
4. 승인된 staging evidence를 주입해 대표 경로를 live 검증한다.
5. 이후 PostGIS/GBIS/model enrichment를 capability별로 활성화한다.

운영 rollback은 deployment factory env를 제거하고 Routing task를 재시작하는 것이다.
그러면 기존 fail-closed unavailable/all-false backend로 복귀한다. Source rollback은
raw adapter, `routing_deployment`, Service production setting과 production-shaped E2E를
각 owner 단위로 되돌린다. 계약, DB migration과 사용자 데이터 rollback은 필요 없다.

## Verification

- 공식 raw success/empty/error/schema-drift fixture가 canonical DTO와 일치한다.
- key/schema/approval/egress evidence 하나라도 없거나 불일치하면 Provider call 0건,
  capability false와 startup/request fail-closed를 확인한다.
- BUS baseline은 `PARTIAL`, null Bus Intelligence, empty model versions와 등록 warning을
  반환하고, no-BUS baseline은 Bus 부재만으로 degrade하지 않는다.
- Service -> HTTP Routing -> production composition -> raw adapter -> graph optimizer ->
  public projection을 fixture use case 없이 별도 process로 통과한다.
- strict taxi upper budget, `P90 >= P50`, chronology, recommendation referential integrity,
  raw/secret/identity redaction과 10/50/100 bounded load를 검증한다.
- repository/contract lock/source layout와 Service/Routing context parity를 재검증한다.

## Supersedes / Superseded By

기존 ADR을 대체하지 않는다. ADR-0003의 두 배포 단위, ADR-0005의 adapter/canonical
경계, ADR-0006의 model artifact 신뢰 경계를 Internal Alpha composition에 적용한다.
