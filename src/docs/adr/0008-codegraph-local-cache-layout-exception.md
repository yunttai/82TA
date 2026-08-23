# ADR-0008: `.codegraph/` 로컬 캐시의 src-only 예외

- 상태: Proposed
- 날짜: 2026-08-23
- 결정자: Service Product owner, Routing & Intelligence owner, contract steward,
  architecture, integration QA, security (approval pending)
- 관련 요구사항: root allowlist, src-only product artifacts, CodeGraph-first code discovery
- 관련 계약: `src/docs/shared/SOURCE_LAYOUT_POLICY.md`,
  `_workspace/integration/CCR-002-codegraph-local-cache-layout-exception.md`

## Context

ADR-0001은 제품 산출물을 `src/` 아래에 두고 제한된 제어면·Git metadata만
root에 허용한다. 사용자가 선택한 CodeGraph 인덱스 `.codegraph/`는 root에
존재하지만 `.gitignore` 대상인 untracked 로컬 캐시이며 제품 산출물이 아니다.
현재 canonical source-layout 정책에는 이 캐시가 없지만 일부 제어·검증 파일은
preflight에서 이를 임시 허용해 정책과 validator가 어긋나 있다.

## Decision

승인될 경우 `.codegraph/`만 다음 조건의 로컬 도구 캐시 예외로 허용한다.

- root의 directory일 것
- Git ignored이며 tracked file이 없을 것
- 제품·계약·테스트·IaC·실행 helper 또는 배포 입력을 포함하는 위치로 쓰지 않을 것
- 존재를 요구하지 않고 인덱싱 여부는 사용자 결정으로 남길 것

이 결정은 아직 Proposed이며 승인 전에는 merge/release source-layout gate를
통과시킨 것으로 간주하지 않는다.

## Alternatives Considered

1. 캐시를 repository 밖으로 이동하거나 제거하고 임시 허용을 철회한다. Canonical
   변경은 없지만 사용자 인덱스 재구성이 필요하다.
2. `.codegraph/`만 좁게 허용한다. CodeGraph-first 작업성과 root 통제를 함께
   유지하므로 제안안으로 선택했다.
3. 모든 hidden cache를 포괄 허용한다. 추적되지 않은 제품·제어 파일을 숨길 수
   있어 거부한다.

## Consequences

- 승인 시 SOURCE_LAYOUT_POLICY, root AGENTS, source-layout skill, validator,
  runbook, validation tests를 하나의 변경으로 정렬해야 한다.
- 제품 bounded context, API, DB 소유권, Provider/model semantics에는 영향이 없다.
- CI는 캐시가 없는 기본 경우와 악성/오구성 present 경우를 모두 검사해야 한다.
- 계약 lock은 양쪽 workstream 승인 뒤에만 갱신한다.

## Security / Privacy / Cost

Validator는 directory·ignored·untracked 조건을 검증해야 한다. Cache는 image,
artifact, SBOM, 배포 bundle에 들어가면 안 된다. 새로운 사용자·위치·Provider
데이터 수집은 없고 외부 비용 변화도 없다.

## Migration and Rollback

승인 경로는 CCR-002 승인, atomic policy/control/test 변경, 양쪽 snapshot parity,
approved lock update 순서다. 거부 시 임시 허용을 revert하고 사용자가 캐시의
이동·삭제·재생성 방식을 선택한다. 자동 삭제는 rollback에 포함하지 않는다.

## Verification

- `.codegraph` absent: layout PASS
- ignored/untracked directory present: layout PASS
- same-name file 또는 tracked child present: layout FAIL
- full repository validation, contract lock, both context snapshots: PASS

## Supersedes / Superseded By

ADR-0001을 대체하지 않으며, 승인 시 그 결정의 좁은 로컬-cache 예외를 추가한다.
