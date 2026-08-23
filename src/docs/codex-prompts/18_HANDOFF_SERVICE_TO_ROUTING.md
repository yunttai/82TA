# 18. 1번→2번 인수인계

**사용 시점:** Service 요구를 Routing에 전달

```text
Service Product의 현재 상태를 Routing & Intelligence에 인수인계할 수 있게 정리해줘. 제품 코드는 수정하지 마라.

- Service WORKPLAN/STATUS/diff/tests를 읽는다.
- Private Routing 계약에서 실제로 소비하는 필드·상태·error/warning을 목록화한다.
- Stub/Replay fixture와 UI 상태 matrix를 연결한다.
- Routing에 필요한 변경은 구현 요청이 아니라 contract/capability/fixture 요구로 작성한다.
- Service가 임시 가정한 부분을 UNVERIFIED로 표시한다.
- _workspace/service-product/HANDOFF.md를 갱신한다.
```
