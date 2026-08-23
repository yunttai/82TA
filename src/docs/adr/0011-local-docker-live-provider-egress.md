# ADR-0011: 로컬 실Provider E2E는 dev provenance와 외부 allowlist proxy를 사용한다

- 상태: Accepted
- 날짜: 2026-08-24
- 결정자: Product owner, Routing & Intelligence owner
- 관련 요구사항: UJ-004, FR-ROUTE-001..005, FR-OPS-001, BR-003, BR-009
- 관련 결정: ADR-0010

## Context

AWS staging을 기다리지 않고 Docker에서 Web → Service → Routing → 실제 Provider →
optimizer → public projection을 검증해야 한다. 기존 production baseline은 의도적으로
STAGING/PRODUCTION만 허용하고, TLS DB와 내부 ALB 및 외부 firewall 증거를 요구한다.
이를 로컬에서 가짜 staging 값이나 허위 firewall attestation으로 우회하면 결과
provenance와 보안 evidence가 거짓이 된다. 반대로 일반 DEVELOPMENT 구성은 Provider
factory가 없고 all-false로 시작하므로 실제 E2E를 실행할 수 없다.

## Decision

1. 별도 `compose.routing-live.yml` overlay를 둔다. 기본 E2E Compose와 production
   배포 정의는 그대로 유지한다.
2. live overlay는 `ROUTING_RUNTIME_ENVIRONMENT=DEVELOPMENT`와 persisted
   `environment=dev`를 유지한다. `ROUTING_LOCAL_LIVE_E2E=true`가 정확히 설정된
   경우에만 production-shaped baseline dependency factory를 허용한다.
3. dev baseline은 mapping/ETA/seat enrichment가 모두 없는 degraded baseline만
   허용한다. staging/prod attestation이 필요한 모델을 dev로 가장하지 않는다.
4. Routing API, PostGIS, Redis는 `internal: true` Docker network에만 연결한다. Routing
   컨테이너은 직접 internet route를 갖지 않는다.
5. 별도 non-root CONNECT proxy만 provider-egress network에 연결한다. proxy는
   `dapi.kakao.com:443`과 `apis-navi.kakaomobility.com:443`만 허용하고, 모든 DNS
   응답이 global address인지 확인한다. Provider path, query, key와 body는 end-to-end
   TLS tunnel 안에 남는다.
6. `.env.local`의 key는 source, generated evidence, Compose config와 로그에 복사하지
   않는다. 준비 스크립트는 operation별 한 번의 고정 probe만 실행하고 key/schema가
   모두 검증된 경우에만 최대 4시간의 단기 evidence를 생성한다.
7. local approval artifact는 bounded Docker session의 호출·quota 승인만 의미하며
   `releaseApproval=false`를 기록한다. staging/production release evidence를 대체하지
   않는다.

## Alternatives Considered

1. **DEVELOPMENT에서 직접 internet egress와 key만으로 활성화한다.** evidence gate와
   defense-in-depth를 제거하므로 거부한다.
2. **로컬 stack을 STAGING으로 표시하고 DB TLS/ALB 값을 가짜로 넣는다.** provenance가
   거짓이고 production setting 검증 의미를 훼손하므로 거부한다.
3. **Service가 Provider를 직접 호출한다.** bounded context와 private Routing 경계를
   깨므로 거부한다.
4. **AWS staging이 준비될 때까지 실제 Provider E2E를 보류한다.** 현재 선택한 Docker
   우선 검증 목표를 달성하지 못하므로 거부한다.

## Consequences

- 한 호스트에서 실제 Provider와 strict optimizer를 반복 검증할 수 있다.
- Docker live 결과는 명확히 `dev`이며 staging/production 출시 증거가 아니다.
- proxy와 evidence 생성기가 추가되지만 key/raw response를 영속화하지 않는다.
- Kakao 외 Provider는 별도 raw adapter, probe, evidence, allowlist가 구현되기 전까지
  key가 있어도 활성화되지 않는다.

## Rollback

두 Compose 파일로 stack을 내리고 generated local evidence/approval 파일을 삭제한다.
기본 `compose.routing-e2e.yml`은 다시 unavailable/all-false DEVELOPMENT 상태로
기동한다. production/staging factory와 Terraform에는 변경이 없다.

## Verification

- proxy URL/CONNECT 응답/TLS 검증 unit test와 proxy exact-host/global-IP infra test
- key나 evidence 누락 시 Provider call 0건과 startup fail-closed
- 실제 3개 Kakao operation probe의 `KEY_AND_SCHEMA_VERIFIED`
- Routing capability/readiness가 exact operation evidence와 일치
- Web → Service → Routing 실제 검색에서 strict taxi upper budget, `P90 >= P50`,
  PARTIAL/null Bus Intelligence, public-safe projection 검증
- generated 파일·container inspect·로그에 Provider key/raw payload가 없음을 확인
