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
- `POST /api/v1/route-searches`의 `422`와 `504`는 이미 구현된 canonical
  Problem 응답을 문서화한 additive response-set correction이다. Private
  `401 SERVICE_AUTH_REQUIRED`는 계속 Public-safe
  `503 TRANSIT_PROVIDER_UNAVAILABLE`로 축약한다.
- 추가된 Public endpoint, optional request/response field, response header, error code는 기존 1.0 consumer를 invalid하게 만들지 않는다.
- 기존 `DELETE /api/v1/me/data`는 유지하고 새 deletion-job endpoint의 compatibility alias로 deprecate한다.
- preference `If-Match`는 1.1 first-party client에 필수인 운영 정책이지만 OpenAPI에서는 1.0 migration window를 위해 optional이다. 미제공 요청 허용은 telemetry 후 제거하며 제거 시 major 또는 별도 versioned endpoint가 필요하다.
- Private `avoidHighBusSeatRisk`와 `busIntelligenceCoverage`는 optional이다. 구 Routing producer/consumer는 각각 값을 무시하거나 coverage를 `UNKNOWN`으로 projection할 수 있다.
- Private request `contractVersion: "1.0"`은 1.x wire compatibility family로 유지한다. OpenAPI metadata와 repository contract version은 `1.1.0`이다.
- Routing `/v1/version.contractVersion`은 그 repository/OpenAPI metadata를
  보고한다. optimize body의 `"1.0"`과 같은 값으로 해석하지 않는다.
- `rankingPolicyVersion`은 opaque provenance다. 현재 실행 정책의 canonical
  식별자는 `rank-0.1.1`이며 Service는 이를 enum화하거나 재계산하지 않는다.
  과거에 저장된 다른 식별자는 당시의 historical provenance로 보존하고
  일괄 재기록하지 않는다.
- 이번 교정은 code enum/registry를 확장하지 않는다. 좌석·버스 근거가
  없으면 provider `messageCode`는 `null`, route/response warning은 등록된
  `BUS_DATA_UNAVAILABLE`를 사용하며 missing 값을 zero risk로 해석하지 않는다.
- DBML은 마지막 target state다. migration은 새 table을 추가하고, 새 `NOT NULL` column은 nullable 또는 safe default로 expand→backfill→constraint 순서를 따른다. old Service binary가 새 schema와 함께 동작하는 overlap 뒤 write/read를 전환한다.
- domain event payload와 event version은 변경하지 않는다. data-rights job은 Service DB 내부 lifecycle이며 cross-workstream event를 새로 요구하지 않는다.
