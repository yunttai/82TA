# Security and Privacy

## 신뢰 경계

```text
Untrusted: browser input, public API traffic, external Provider response
Semi-trusted: authenticated Service request, cache, user feedback
Trusted internal: private Routing API, approved model registry, production DB
```

외부 Provider 응답도 schema·범위·시각 검증 전에는 신뢰하지 않는다.

## 주요 위협과 통제

| 위협 | 통제 |
|---|---|
| API key 유출 | Secrets Manager, 최소 권한, rotation, browser 비노출 |
| Denial of Wallet | WAF, rate limit, cache, candidate/provider call 상한, cost alarm |
| SSRF | Provider URL allowlist, 사용자 URL 금지, egress 제어 |
| 위치 이력 노출 | 최소 저장, encryption, redaction, 삭제 |
| 계정 탈취 | secure cookie, CSRF, login rate limit, audit |
| Routing API 위조 | private network, service JWT/workload identity |
| cache poisoning | canonical key, response validation, ACL |
| model artifact RCE | registry, native safe format, hash/signature, fixed path |
| dependency supply chain | lockfile, SBOM, SAST/SCA, image/IaC scan |
| mapping 오류 | precision-first threshold, LOW 미적용, review queue |
| Provider schema drift | validation, degraded state, alert, fixture 격리 |

## 위치 처리

- 검색 시 정확한 좌표는 계산 목적에만 사용한다.
- Routing에는 user identity를 보내지 않는다.
- 로그·trace에는 낮은 정밀도 region만 사용한다.
- saved place와 route history는 명시적 저장·삭제를 지원한다.
- 분석 dataset에는 정확한 좌표와 `집/직장/학교` label을 복사하지 않는다.

## 내부 서비스 인증

- internal load balancer/private subnet
- Service task만 ingress 허용
- 짧은 수명의 signed JWT 또는 workload identity
- `iss`, `aud`, `exp`, `jti` 검증
- caller·correlation audit

## Secure SDLC

- branch protection과 mandatory review
- secret scanning
- SAST·dependency·container·IaC scan
- SBOM과 image provenance
- contract compatibility와 migration check
- production 관리자 MFA
- model activation·mapping override·data export audit

## 상용 출시 검토

- Kakao·Kakao Mobility 상용 사용·저장·표시 조건
- TMAP·ODsay 저장 제한
- GBIS·GITS·KMA 출처·이용조건
- 국내 개인정보·위치정보 관련 의무
- 택시비·ETA·승차 가능성 표현의 오인 가능성
