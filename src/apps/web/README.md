# React Web App / PWA

모바일 우선 React+TypeScript 설치형 PWA다. iPhone Safari와 Android Chrome의
홈 화면 설치, safe-area, `100dvh`, 16px form input을 고려한다. 브라우저는 생성된
`@82ta/service-client`를 통해 같은 origin의 Public Service API만 호출한다.
검색 전 `GET /api/v1/health`로 CSRF cookie를 bootstrap하고, 요청 직전에 읽은
`csrftoken`을 `X-CSRFToken`으로 설정해 `POST /api/v1/route-searches`를 호출한다.
두 요청 모두 `credentials: same-origin`이며 토큰은 저장하거나 로그로 남기지
않는다.

## 제공 화면과 흐름

`IDLE → VALIDATING → SEARCHING` 이후 Public API의 semantic status인
`COMPLETE`, `PARTIAL`, `NO_FEASIBLE_ROUTE`, `PROVIDER_UNAVAILABLE`, `FAILED`,
`EXPIRED` 중 하나를 표시한다. 응답 만료시각이 지나면 화면도 `EXPIRED`로
전환한다.

- `/`: Service 장소 추천·현재 위치·Kakao 입력 지도 좌표 선택, canonical 제약,
  허용 교통수단과 경로 검색
- `/searches/:searchId[/routes/:routeId[/bus/:legId]]`: 저장 결과·경로·구간 deep link
- `/history`, `/places`, `/favorites`: 동의 기반 기록과 저장 자원
- `/preferences`: ETag/If-Match 충돌을 포함한 사용자 선호
- `/me`, `/account`, `/privacy`, `/support`: guest session, 동의, export/삭제 job, capability
- `SearchForm`: canonical 제약 기본값과 WGS84 좌표 입력 검증
- `useRouteSearch`: generated request/response 타입, idempotency/correlation,
  semantic state transition
- `ResultPanel`: 네 추천, null 추천, warning/reason, capability, leg 및
  Bus Intelligence 표시
- `publicService`: generated runtime client의 Public API 경계

Route 시간·비용·ranking·확률은 재계산하지 않는다. Kakao 지도는
`VITE_KAKAO_MAP_APP_KEY`가 있고 실제 GeoJSON geometry가 있을 때만 그린다.
GEOJSON과 bounded standard POLYLINE만 검증 후 표시하며 geometry가 없거나
malformed/oversized이면 직선으로 위장하지 않는다.
현재 위치와 guest token은 page memory에서만 사용하며 브라우저 저장소나 로그에
남기지 않는다. Service Worker는 shell/정적 asset만 캐시하고 `/api/**`는 절대
가로채거나 캐시하지 않는다.

Public 1.2.0의 이메일 회원가입·로그인은 HttpOnly Django session으로 처리한다.
아직 계약에 없는 계정 복구·이메일 확인·guest merge, 개별 검색 기록 삭제,
consent 문서 배포는 임의 endpoint 없이 미지원 상태로 남긴다.
동의 변경과 production build를 활성화하려면 배포 환경에서
`VITE_PRIVACY_DOCUMENT_VERSION`을 Service가 현재 게시한 동의 문서 version과
정확히 같은 값으로 설정해야 한다. 누락되거나 안전한 version 형식이 아니면
production build가 실패한다. 값은 계약 version을 대신 쓰거나 프론트에
hardcode하지 않는다. `.env.example`은 변수 이름만 제공한다.

## 실행

```bash
npm install
npm run typecheck
npm test
VITE_PRIVACY_DOCUMENT_VERSION=<서버-게시-문서-version> npm run build
npx playwright install chromium webkit
VITE_PRIVACY_DOCUMENT_VERSION=<서버-게시-문서-version> npm run test:e2e
```

개발 서버의 `/api` 요청은 기본적으로 `http://127.0.0.1:8000`의 Django
Service Backend로 proxy된다. 포트가 사용 중이면 예를 들어
`VITE_SERVICE_API_PROXY=http://127.0.0.1:18000 npm run dev`로 변경한다.
실기기 배포 전에는 HTTPS, Kakao JavaScript key의 도메인 allowlist,
`VITE_PRIVACY_DOCUMENT_VERSION`을 설정하고 iPhone Safari/Android Chrome에서
설치·업데이트·오프라인·위치 권한을 확인한다. Linux WebKit 실행은 Playwright가
안내하는 host library 설치가 추가로 필요할 수 있다.
