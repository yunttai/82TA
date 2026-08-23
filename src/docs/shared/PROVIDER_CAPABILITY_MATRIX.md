# Provider Capability Matrix

## 상태 모델

```text
DOCUMENTED          공식 문서에서 기능 확인
KEY_VERIFIED        프로젝트 key로 호출·schema 확인
PRODUCTION_APPROVED 약관·quota·비용·상용 조건 승인
```

## 초기 상태

| Provider / 기능 | 문서 | Key | Production | 역할 | Fallback |
|---|---|---|---|---|---|
| Kakao Local | DOCUMENTED | 보유·검증 필요 | 검토 | 장소·주소 | 추가 geocoder |
| Kakao Maps JS | DOCUMENTED | 보유 | domain 설정 필요 | 지도 렌더링 | 없음 |
| Kakao Public Transit | DOCUMENTED | 미시험 | 검토 | 현재 transit baseline | TMAP·ODsay |
| Kakao Walk | DOCUMENTED | 미시험 | 검토 | access/transfer/egress walk | transit 내부 walk |
| Kakao Directions | DOCUMENTED | 성공 | 검토 | taxi time/fare | 대체 driving provider |
| Kakao Multi Destination | DOCUMENTED | 미시험 | 검토 | hub coarse ranking | bounded single directions |
| Kakao Multi Origin | DOCUMENTED | 미시험 | 검토 | egress coarse ranking | bounded single directions |
| Kakao Future Directions | DOCUMENTED | 미시험 | 검토 | 미래 taxi | historical model/unsupported |
| GBIS v2 | DOCUMENTED | key 보유 | 데이터 조건 검토 | bus arrival/location/seat | recent cache/historical |
| KMA | DOCUMENTED | key 보유 | 출처·저장 검토 | weather | recent valid snapshot |
| GITS | DOCUMENTED | 접근 확인 필요 | 검토 | bus ETA road context | Kakao traffic/historical |
| TMAP Transit | DOCUMENTED | 선택 | 요금·24h 저장 검토 | future transit fallback | ODsay/historical |
| ODsay | DOCUMENTED | 선택 | 요금·저장 검토 | structure/ID 보조 | 없음 |

## Provider 선택 규칙

- 공식 endpoint 존재와 현재 key 사용 가능을 구분한다.
- current transit과 future transit capability를 분리한다.
- 서로 다른 Provider의 total time을 근거 없이 평균하지 않는다.
- 이름만 같은 route·stop을 동일 entity로 확정하지 않는다.
- 저장 제한이 있는 응답을 학습 dataset에 장기 저장하지 않는다.

## Online 호출

- current transit
- exact taxi route/fare
- 필요한 GBIS arrivals/locations

## 사전 수집

- route/stop master
- KMA·GITS context
- holiday/event
- long-term bus observations
- Provider capability/schema health
