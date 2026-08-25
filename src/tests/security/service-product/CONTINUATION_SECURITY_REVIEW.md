# SP-CONT-250 Service Product 보안 검토

- 검토일: 2026-08-23 (Asia/Seoul)
- 계약: `1.1.0`
- 계약 lock: `80ade2452c103c534ac88deb5b832d21c27d0bd8eee8d5c5f270bb5491ffdb1a`
- 범위: React Web/PWA session·retry·result, Django Redis coordination/HMAC,
  Routing/Kakao response trust, PostGIS, data retention, GCE IaC, generated client tracking
- 변경 권한: 이 보안 evidence/test 디렉터리만 수정; 제품 코드는 읽기 전용 검토

## 판정

검토한 현재 Service 소스에서 알려진 Critical/High 취약점은 각각 0건이다.
Canonical Stub/Replay를 사용하는 local/CI vertical slice는 보안 관점에서 `GO`다.

Internet staging/closed beta/GA는 `NO-GO`다. 이 판정은 알려진 Critical/High
코드 취약점이 아니라 실제 GCE Nginx client-IP chain, PostGIS/Redis,
Kakao 운영 키, Private Routing, data-rights 전달·삭제 및 실제 모바일 기기
evidence가 아직 없기 때문이다.

## Threat/data-flow delta

```text
Browser module memory
  guest bearer + exact retry body + cryptographic idempotency key
    └─ same-origin HTTPS / CSRF / no-store
       GCE Nginx + Let's Encrypt HTTPS
         └─ Django Service
            ├─ Redis TLS: atomic quota + owner-scoped single-flight/replay (10분)
            ├─ PostgreSQL/PostGIS geography(Point,4326): exact Service location
            ├─ Kakao Local fixed HTTPS origin: server-only REST credential
            └─ Private Routing exact HTTPS allowlist + Service bearer
                 identity/label/place-id/history stripped; HMAC key only
```

- guest token, last request, retry idempotency key는 Web module memory에만 있으며
  local/session storage, IndexedDB, service-worker cache에 기록하지 않는다.
- 불확실한 네트워크 결과의 명시적 retry는 같은 body와 idempotency key를
  재사용한다. 만료 결과는 새 검색으로 분리한다.
- Redis key는 keyed HMAC이고 raw IP, user/guest ID, public idempotency key를
  포함하지 않는다. completed public response는 600초 TTL이며 TLS 및 encrypted
  GCE runtime 경계 안에 있다. managed Redis를 도입할 경우 TLS는 certificate와 hostname 검증을 요구한다.
- Routing에는 좌표와 canonical constraints만 전달한다. Service owner와 public
  retry key는 HMAC으로 가리고 display name, provider place ID, history, email,
  guest token은 전달하지 않는다.
- Routing과 Kakao 응답은 redirect를 따르지 않고 고정 origin/host를 사용하며,
  선언된 길이와 chunked body 모두 byte ceiling 안에서만 generated parser/JSON
  parser로 넘긴다.
- exact coordinate는 PostGIS `geography(Point,4326)`로 저장하며 finite/WGS84/SRID
  검증을 거친다. transient 결과는 Routing expiry와 무관하게 짧은 Service TTL로
  제한되고 history는 current consent가 있어야 저장한다.
- export는 Fernet 암호화된 private filesystem artifact이며 path escape를 거부한다.
  TTL purge는 artifact를 물리 삭제하고, artifact 삭제 실패 시 reference 및 계정
  hard-delete가 fail-closed한다. GCE volume backup도 canonical TTL을 무단 연장하지 않아야 한다.

## 실행 evidence

| 검증 | 결과 |
|---|---:|
| Service security | 32/32 PASS |
| Django Service 전체 | 116/116 PASS |
| production `check --deploy --fail-level WARNING` | warning 0 |
| Python dependency audit | 알려진 취약점 0; local generated client는 PyPI 미등록으로 제외 |
| Frontend Vitest | 41/41 PASS |
| TypeScript / production build | PASS |
| npm audit | 0 vulnerabilities |
| mobile Chromium E2E/axe | 3/3 PASS |
| mobile WebKit | 환경 library 부재로 browser launch 전 0/3 BLOCKED |
| Infra static | 8/8 PASS |
| generated client tracking | 3/3 PASS |
| generated client clean regeneration | reproducibility PASS |
| repository / contract lock | PASS |
| Service↔Routing context parity | PASS |

Security suite가 추가로 고정하는 continuation assertion:

- memory-only guest/session과 cryptographic retry key
- 동일 body/idempotency-key retry
- owner-scoped Routing HMAC identity stripping
- Redis certificate/hostname verification
- compressed upstream body의 parsing/decompression 전 거부와 strict raw-byte ceiling
- CSRF, IDOR, XSS, PWA API-cache exclusion, exact-location log exclusion
- encrypted export, path confinement, TTL physical purge, hard delete

## 해소된 finding과 남은 release gate

### SEC-M-CONT-01 — 해소: GCE trusted-proxy viewer quota identity

- 심각도: Medium (availability/Denial of Wallet defense)
- flow: viewer → GCE Nginx `X-Forwarded-For` append/sanitize → Django nearest-untrusted hop
- GCE Compose가 exact private proxy CIDR만 trusted proxy로 주입한다. reverse walk는
  trusted Nginx hop을 건너뛰고 viewer IP를 선택하며, viewer가 만든 왼쪽 XFF 값은 무시한다.
- Routing은 host port를 공개하지 않으며 arbitrary range나 dedicated spoofable identity
  header는 사용하지 않는다.
- static chain test와 many-CIDR settings test는 통과했다. 실제 GCE ingress header
  capture/multi-user quota smoke는 internet staging 운영 gate로 유지한다.

### SEC-L-CONT-02 — 해소: caller correlation의 내부 log privacy

- 심각도: Low
- public 응답 correlation은 기존 호환성을 유지하지만 Private Routing에는 Service가
  새 opaque UUID를 생성해 전달한다. caller-selected PII/좌표형 문자열은 Service
  trust boundary 밖의 내부 log key로 전달되지 않는다.

### SEC-M-CONT-03 — 해소: Provider/Routing response amplification

- Routing 2 MiB, Kakao Local 512 KiB의 설정 상한을 적용한다. `Content-Length`와
  chunked raw body를 모두 검사하고 `Accept-Encoding: identity`를 강제한다.
- upstream이 non-identity `Content-Encoding`을 반환하면 body를 소비하거나 압축
  해제하기 전에 거부해 decompression bomb의 선행 allocation도 막는다.
- generated artifacts를 직접 수정하지 않고 generated operation의 request/response
  builder를 bounded adapter로 감싸므로 clean regeneration 뒤에도 제어가 유지된다.

### 계약·운영 gate

- USER 가입·로그인·복구·guest merge canonical 계약과 구현
- authenticated one-time export download 계약/endpoint 및 live GCE volume worker·TTL 삭제 drill
- 실제 GCE TLS/CSP/edge control, PostGIS migration/restore, Redis failover/rotation evidence
- 실제 Kakao JavaScript/REST key domain·app restriction과 위치정보 고지/법률 검토
- 실제 Private Routing compatibility, response-size/load/cost/rollback drill
- WebKit 실행 의존성 및 실제 iPhone Safari·Android Chrome/PWA 설치·업데이트 검증
- generated sources를 최종 commit에 포함한 clean-checkout regeneration 확인

## 계약 영향과 rollback

- OpenAPI, DBML, code registry, 계약 lock 변경 없음.
- Service에서 Provider orchestration, model, ETA/seat, 후보 생성, ranking을 구현하지 않았다.
- 이 검토의 rollback은 `test_full_service_security.py`의 continuation assertion과 이 문서만
  되돌린다. 제품/계약/인프라 파일은 이 보안 작업에서 수정하지 않았다.
