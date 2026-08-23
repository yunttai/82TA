# Contract Change Protocol

## Compatible Examples

- optional provenance field
- new warning code with generic consumer fallback
- new endpoint
- optional capability boolean

## Breaking Examples

- seconds를 minutes로 변경
- taxi expected 기준을 upper 기준으로 의미 변경
- required field 추가
- enum 삭제·rename
- opaque routing ID를 DB PK로 노출

## Review Questions

1. 어느 context가 계산·저장 책임을 가지는가?
2. consumer가 이 값 없이 안전하게 동작할 수 있는가?
3. 위치·identity·Provider 약관 영향은 있는가?
4. 이전 version과 동시에 배포 가능한가?
5. replay와 field test에서 무엇을 검증할 것인가?
