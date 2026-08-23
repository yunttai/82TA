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
