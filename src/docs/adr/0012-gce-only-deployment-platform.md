# ADR-0012: GCE를 유일한 cloud compute 배포 플랫폼으로 사용한다

- 상태: Accepted
- 날짜: 2026-08-25
- 결정자: Product owner
- 관련 요구사항: NFR-REL-001..004, NFR-SEC-001..004, NFR-OPS-001..003
- 대체 결정: 과거 다른 cloud 기준 IaC·배포 문서

## Context

실제 main/tag CD는 빈 GCE VM에 Docker Compose를 배포하지만, 공유 문서와 대규모
Terraform, 비활성 CI template, 보안 검증은 별도 cloud managed-service 구성을
기준으로 삼고 있었다. 이 불일치는 하네스가 존재하지 않는 배포를 요구하고 현재
구성을 잘못된 것으로 판정하게 만들었다. Product owner는 GCE 사용을 필수로
결정했고 dual-cloud 운영은 요구하지 않았다.

## Decision

1. GCE를 유일한 지원 cloud compute 플랫폼으로 사용한다.
2. 현재 배포 기준은 GCE VM 한 대, Docker Compose, Nginx/Let's Encrypt, host
   bootstrap 및 `.github/workflows/cd-gce.yml`이다.
3. 기존의 다른 cloud Terraform, runbook, CI template은 제거한다. 호환성이나
   parity를 유지하지 않는다.
4. Terraform은 현재 경로에 필요한 GCE VM, network, static IP, firewall,
   service account와 versioned/private Cloud Storage만 제공한다.
5. Routing model/data artifact의 cloud URI는 `gs://`를 사용하며 hash와 immutable
   materialization mapping을 계속 검증한다.
6. GCE 사용은 필수지만 exact topology는 고정하지 않는다. 실제 필요가 생기면
   Google Cloud 안에서 여러 GCE VM, managed instance group, Cloud Load Balancing,
   Cloud Armor, Cloud SQL, Memorystore, Artifact Registry, Secret Manager,
   Cloud Logging/Monitoring을 선택할 수 있다.
7. 현재 Compose의 development/runtime flags와 Service SQLite를 production으로
   재명명하지 않는다. 환경 승격은 별도 운영 evidence로 판단한다.

## Alternatives Considered

1. **실제 GCE CD와 별개로 기존 cloud target을 문서·IaC에 유지한다.** 지속적인
   drift와 잘못된 gate를 만들므로 거부한다.
2. **cloud-neutral 문서만 두고 구현 플랫폼을 선택사항으로 둔다.** GCE 필수라는
   제품 결정을 표현하지 못하므로 거부한다.
3. **현재 Compose를 즉시 production settings로 전환한다.** 필요한 PostgreSQL,
   Redis TLS, Service→Routing TLS, backup/restore evidence가 없어 기동을 깨뜨리므로
   거부한다.
4. **GCE의 특정 managed-service 조합까지 영구 고정한다.** 현재 구현과 필요보다
   앞선 규제가 되므로 거부한다.

## Consequences

- 문서, IaC, active workflow와 검증의 cloud 기준이 GCE로 일치한다.
- 운영자는 두 cloud의 계정, IAM, 비용, 복구 체계를 병행하지 않는다.
- 기존 다른 cloud 배포로의 자동 rollback은 지원하지 않는다.
- 단일 VM의 가용성·데이터 지속성 한계는 사라지지 않으며 production 승격 전에
  명시적으로 해소하거나 수용해야 한다.

## Rollback

이 결정의 rollback은 새 ADR과 명시적 Product owner 승인 없이는 수행하지 않는다.
애플리케이션 배포 rollback은 같은 GCE 환경에서 직전 image/Compose revision으로
수행한다. Terraform 변경은 reviewed plan과 GCS state version을 사용해 되돌린다.

## Verification

- 저장소 infra/workflow에 다른 cloud provider resource가 없음을 정적 검사
- GCE Terraform format/validate와 module 구조 검사
- active GCE build→bootstrap→ordered deploy→HTTPS health 순서 검사
- `gs://` artifact URI positive/negative tests
- repository validation과 canonical context lock verification
