# Service Product 최종 보안 검토

- 검토일: 2026-08-23 (Asia/Seoul)
- 계약: `1.1.0`
- 계약 lock: `80ade2452c103c534ac88deb5b832d21c27d0bd8eee8d5c5f270bb5491ffdb1a`
- 범위: React Web/PWA, Django Public Service, Kakao Local adapter, `HttpRoutingGateway`, Service 배포 IaC
- 제외: Routing 내부 Provider·모델·ranking 구현

## 판정

검토한 Service 소스의 알려진 Critical/High 취약점은 0건이다. Canonical Stub/Replay를 사용하는 로컬·CI vertical slice는 보안 관점에서 GO다.

인터넷 staging, closed beta, GA는 아직 NO-GO다. 이 판정은 알려진 Critical/High 코드 취약점 때문이 아니라 아래 운영·기능 evidence가 아직 없기 때문이다.

1. 실제 AWS에서 CloudFront → 사용자 지정 origin DNS → TLS ALB → ECS 흐름, CSP/WAF, RDS/PostGIS migration을 검증한 smoke evidence
2. 완료된 export를 사용자에게 전달하는 authenticated one-time download의 canonical 의미·구현과 실제 EFS/worker/삭제 drill
3. USER 가입·로그인·복구와 guest-to-user merge의 canonical 계약 및 구현
4. Kakao JavaScript 키의 운영 도메인 제한, Provider 약관·위치정보 고지 및 법률 검토
5. 실제 Routing 연결에서 부하·비용 상한, 다중 worker idempotency, 장애·rollback drill

## Trust boundary와 데이터 흐름 delta

```text
Browser/PWA
  └─ HTTPS + same-origin cookie/CSRF
     CloudFront(CSP, no API cache) + WAF(IP/path rate limits, query redaction)
       └─ HTTPS-only custom origin DNS + ALB
          └─ private ECS Service API
             ├─ encrypted Service PostgreSQL: identity, exact location, history, consent
             ├─ KMS EFS + Fernet: 15분 data export; EventBridge worker/purge + encrypted DLQ
             ├─ Kakao Local: fixed HTTPS origin/path, REST key server-only, no redirect
             └─ Routing API: exact HTTPS host allowlist + service bearer
                └─ coordinates/constraints only; user identity, labels, history are stripped
```

- PWA service worker는 same-origin GET 정적 자산만 다루고 `/api/**`를 항상 우회한다.
- Public API 응답과 위치 검색 응답은 `Cache-Control: no-store`다.
- guest bearer는 고엔트로피로 발급하며 DB에는 SHA-256 digest만 저장한다.
- 사용자 위치·장소·이력·동의·data-rights job은 Service DB에만 저장한다. Routing으로 사용자 ID, 이메일, guest token, 장소 표시명, Provider place ID, `saveToHistory`를 전달하지 않는다.
- reverse-geocode의 정확한 좌표는 canonical GET query에 있으므로 로그 경계에서 차단했다. Gunicorn 및 nginx API access log는 꺼져 있고 ALB access log는 생성하지 않는다. WAF는 authorization, cookie, query string을 redact하며 request sampling도 끈다. AWS 문서상 ALB request line은 URL을 포함하고, WAF redaction은 sampling에 적용되지 않으므로 두 제어가 모두 필요하다: [ALB access logs](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-access-logs.html), [WAF logging](https://docs.aws.amazon.com/waf/latest/developerguide/logging-management.html).

## 검증 결과

| 영역 | 결과 | 주요 assertion |
|---|---:|---|
| CSRF/session | PASS | unsafe mutation 403, secure/same-site/httpOnly production cookie, guest hash-only |
| IDOR | PASS | 다른 사용자의 장소·검색·data-rights job은 404, mutation 없음 |
| XSS/credential | PASS | dangerous HTML/eval/credential storage/console/private Routing sink 없음 |
| PWA cache | PASS | same-origin GET only, `/api/**`와 민감 storage 제외 |
| Routing gateway | PASS | production HTTPS, exact hostname, origin-only URL, userinfo/path/query/fragment/redirect 거부 |
| Kakao Local | PASS | 고정 `https://dapi.kakao.com`, 고정 path, redirect 거부, canonical schema 검증 |
| DoW/rate limit | PASS | route/place/guest scoped application 429 + edge WAF rate controls |
| Proxy trust | PASS | forwarding header 기본 제거, 명시 CIDR의 nearest-untrusted hop만 사용 |
| 개인정보 log | PASS | Gunicorn/nginx/ALB/WAF 정적 배포 assertion |
| consent | PASS | server-owned current version 불일치 거부, current acceptance만 history/feedback 허용 |
| export/delete lifecycle | PASS(static) | worker 상태전이, Fernet 암호화, path escape 거부, TTL 물리 삭제, artifact 삭제 실패 시 계정 삭제 fail-closed |
| encrypted deployment | PASS(static) | KMS RDS/Redis/S3/logs/secrets/EFS, TLS+IAM access point, non-root read-only ECS, EventBridge/DLQ |
| dependency audit | PASS | npm 0건, Python 0건; generated local Routing client는 PyPI 미등록이라 감사 제외 |

실행 명령:

```bash
cd src/services/service-api
uv run python manage.py test /home/caterpii/bob/devton/src/tests/security/service-product
uv run python manage.py test
uvx pip-audit --path .venv/lib/python3.13/site-packages

cd /home/caterpii/bob/devton
python3 -m unittest discover -s src/infra/tests -p 'test_*.py' -v
python3 src/scripts/verify_contract_lock.py
python3 src/scripts/validate_repository.py
```

최종 측정값:

- Service security: 28/28 PASS
- Django Service 전체: 88/88 PASS
- production Django deploy check: warning 0
- frontend Vitest: 28/28 PASS; typecheck/production build PASS; npm audit 0건
- 모바일 Chromium E2E/axe: 3/3 PASS; 실제 iOS/Android device는 미검증
- Infra static: 7/7 PASS; Terraform init/validate PASS(인프라 담당 evidence)
- Python audit: 알려진 취약점 0건; generated local Routing client는 PyPI 감사 제외

## 남은 finding과 gate

### SEC-M-01 — trusted response byte/schema hardening

- 심각도: Medium
- flow: private Routing response → Service public projection → browser map
- 영향: 잘못되거나 손상된 trusted Routing 응답이 매우 큰 JSON을 반환하면 Service가 response parsing 단계에서 CPU/메모리를 과도하게 쓸 수 있다.
- 현재 제어: frontend는 POLYLINE 100,000자, POLYLINE/GEOJSON 10,000 point, GEOJSON nesting depth 4로 제한하고 좌표 range를 검사한다. malformed/oversized geometry는 그리지 않고 명시한다.
- 조치: HttpRoutingGateway response byte 상한과 canonical `Geometry.value` size/shape 계약 change request.
- gate: staging load/adversarial fixture 전까지 추적. 현재 trusted 내부 source이므로 Critical/High blocker는 아니다.

### SEC-M-02 — 다중 worker idempotency/application quota

- 심각도: Medium
- flow: public route retry → 여러 Gunicorn/ECS worker → Routing 비용
- 영향: process-local idempotency/cache는 worker 간 replay를 보장하지 않아 중복 Routing call 또는 409가 발생할 수 있다.
- 현재 제어: owner-scoped key, request fingerprint, DB unique routing request ID, bounded TTL cache, CloudFront WAF path/IP rate limits.
- 조치: staging 전 Redis-backed atomic idempotency와 quota를 연결하고 retry/load evidence를 남긴다.

### PRIV-G-01 — data-rights 전달 계약과 live 삭제 evidence

- 유형: privacy/release gate; 확인된 exploit이 아님
- 코드 상태: bounded worker와 management command가 PENDING job을 소비한다. export는 Fernet 암호화 파일로 기록되고 15분 TTL 후 물리 삭제된다. artifact 삭제 실패 시 DB reference를 유지하고 계정 hard-delete도 fail-closed한다. IaC는 KMS EFS(TLS/IAM access point), EventBridge 5분/1시간 schedule, encrypted DLQ와 alarm을 선언하며 EFS backup은 TTL 연장을 막기 위해 끈다.
- 남은 연결: Public `DataRightsJob.downloadUrl`은 COMPLETE에서도 항상 `null`이다. frozen 계약에는 download URL의 발급·인증·단회성·폐기 의미와 download endpoint가 없다. 임의 endpoint를 추가하지 말고 contract change request가 필요하다.
- live evidence: 실제 secret seed/key rotation, export 생성·복호화 전달·TTL 삭제, 계정 삭제, DLQ/alarm, DB backup·외부 analytics 삭제 drill.
- gate: export/delete 완료 기능을 beta/GA에서 주장하기 전에 필수다. worker/저장소 소스 결함은 해소됐고, 남은 항목은 계약·운영 gate다.

### OPS-G-01 — live staging evidence

- 유형: deployment gate
- 정적 제어: HTTPS-only ALB origin과 matching DNS/certificate precondition, CloudFront WAF/CSP, RDS PostgreSQL 암호화, Secrets Manager, migration-before-deploy workflow.
- 미검증: 실제 인증서 hostname, secret 값, Kakao 키 domain restriction, Terraform plan/apply, PostGIS migration, restore/rollback, iOS/Android 실제 기기.

## Release/rollback

- local/CI Stub·Replay: GO
- Internet staging: NO-GO until `PRIV-G-01` live drill, live TLS/CSP/WAF/Postgres smoke, secret/key restriction evidence
- closed beta/GA: NO-GO until USER auth contract, data-rights drill, provider/legal/privacy review, cost/load/rollback evidence
- 보안 테스트 변경 rollback: `src/tests/security/service-product/test_initial_vertical_slice_security.py`, `test_full_service_security.py`, 이 문서만 되돌린다. 제품 코드·계약 rollback은 이 검토에서 수행하지 않았다.
