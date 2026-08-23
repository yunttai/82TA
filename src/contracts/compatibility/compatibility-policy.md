# Contract Compatibility Policy

## Major Change

- required field 삭제·이름 변경
- field 의미·단위 변경
- enum 값의 기존 의미 변경
- endpoint 제거·method 변경
- null 가능성을 제거해 기존 응답이 invalid가 됨

major URL 또는 compatibility adapter가 필요하다.

## Compatible Minor Change

- optional field 추가
- optional endpoint 추가
- reason/warning code 추가
- unknown enum 처리를 전제로 한 enum 추가

## 배포 순서

1. Producer가 optional field와 old behavior를 함께 제공
2. Consumer가 새 generated client로 갱신
3. Feature flag로 사용
4. 사용률·오류 telemetry 확인
5. deprecation 공지와 기간
6. old field 제거는 major 또는 합의된 migration window

## Gate

- OpenAPI diff
- generated client diff
- producer contract test
- consumer contract test
- example fixture validation
- DB migration compatibility
- context/contract lock update
- 양쪽 contract guardian 승인

## 1.1.0 compatibility decision

- 분류: backward-compatible minor.
- 추가된 Public endpoint, optional request/response field, response header, error code는 기존 1.0 consumer를 invalid하게 만들지 않는다.
- 기존 `DELETE /api/v1/me/data`는 유지하고 새 deletion-job endpoint의 compatibility alias로 deprecate한다.
- preference `If-Match`는 1.1 first-party client에 필수인 운영 정책이지만 OpenAPI에서는 1.0 migration window를 위해 optional이다. 미제공 요청 허용은 telemetry 후 제거하며 제거 시 major 또는 별도 versioned endpoint가 필요하다.
- Private `avoidHighBusSeatRisk`와 `busIntelligenceCoverage`는 optional이다. 구 Routing producer/consumer는 각각 값을 무시하거나 coverage를 `UNKNOWN`으로 projection할 수 있다.
- Private request `contractVersion: "1.0"`은 1.x wire compatibility family로 유지한다. OpenAPI metadata와 repository contract version은 `1.1.0`이다.
- DBML은 마지막 target state다. migration은 새 table을 추가하고, 새 `NOT NULL` column은 nullable 또는 safe default로 expand→backfill→constraint 순서를 따른다. old Service binary가 새 schema와 함께 동작하는 overlap 뒤 write/read를 전환한다.
- domain event payload와 event version은 변경하지 않는다. data-rights job은 Service DB 내부 lifecycle이며 cross-workstream event를 새로 요구하지 않는다.

## 1.2.0 compatibility decision

- 분류: backward-compatible Public API minor.
- 이메일 가입·로그인 endpoint는 additive이며 기존 guest/session consumer 동작을 바꾸지 않는다.
- `SessionContext.email`은 optional이고 USER 본인 session 응답에만 포함한다. 1.1 consumer는 이를 무시할 수 있다.

## 1.3.0 compatibility decision

- 회원가입 요청은 전용 `EmailRegistrationInput`으로 확장한다. 로그인 요청의 `EmailCredentialInput`은 유지한다.
- `SessionContext.nickname`은 optional additive field이며 USER 본인 session에만 포함한다.
- 기존 profile은 migration에서 비식별 기본 닉네임 `82TA 사용자`로 채운다.
- 필수 개인정보 처리 동의는 가입 시 true여야 하고, 네 선택 목적은 독립 boolean으로 명시한다.
- Routing Private API와 Routing DB에는 영향이 없다.
- Service DBML의 기존 `auth_user.email`과 `password_hash`, `authenticated_session`을 사용하므로 shared DB target shape와 Routing boundary에는 변화가 없다.
- 로그인 실패는 `INVALID_CREDENTIALS`, 중복 가입은 `ACCOUNT_ALREADY_EXISTS`로 표현하며 기존 오류 코드는 유지한다.
- Routing OpenAPI, domain event payload와 event version은 변경하지 않는다.
