# GCE Deployment Baseline

## 1. 결정

GCE는 82TA의 유일한 지원 cloud compute 배포 기준이다. 다른 cloud용 IaC,
runbook, CI/CD 경로와 dual-cloud parity는 유지하지 않는다. GCE 사용 자체는
필수지만, VM 수나 managed service 조합까지 하네스가 고정하지는 않는다.

## 2. 현재 구현

현재 배포 경로는 하나의 GCE VM에서 다음 구성을 실행한다.

- 외부 진입: 고정 external IP, Nginx, Let's Encrypt HTTPS
- 애플리케이션: Web, Service API, private Routing API Docker containers
- Routing state: VM 내부 PostGIS와 Redis containers
- Service state: persistent host volume의 SQLite
- image registry: 현재 CD가 사용하는 Docker Hub
- 배포: `.github/workflows/cd-gce.yml`의 pinned-host SSH bootstrap/deploy
- model/data artifact identity: versioned Cloud Storage의 `gs://` URI

Routing API는 host port를 공개하지 않고 Service API만 private Docker network로
호출한다. 현재 Compose의 development/runtime flag와 Service SQLite는 실제 구현을
나타내며, 이름이 `prod`라는 이유만으로 production readiness를 주장하지 않는다.

## 3. Terraform 범위

`src/infra/terraform/modules/gce-platform`은 현재 배포가 요구하는 GCE VM,
VPC/subnet, 고정 IP, 80/443 및 명시적 SSH ingress, Shielded VM, 전용 service
account, versioned/private Cloud Storage artifact bucket을 만든다. Terraform
state는 별도로 bootstrap한 versioned GCS bucket에 둔다. secret 값은 Terraform
입력이나 state에 넣지 않는다.

## 4. 변경 허용 범위

실제 부하와 운영 요구가 생기면 같은 Google Cloud 안에서 여러 GCE VM, managed
instance group, Cloud Load Balancing, Cloud Armor, Cloud SQL, Memorystore,
Artifact Registry, Secret Manager, Cloud Logging/Monitoring으로 진화할 수 있다.
이들은 현재 구현되지 않았으므로 필수 완료 항목으로 간주하지 않는다.

## 5. 승격 조건

staging/production 표시는 환경별 evidence가 있을 때만 사용한다.

- Service PostgreSQL/Redis 또는 단일-node 제약을 수용한 명시적 운영 결정
- Service→Routing trusted TLS와 실제 proxy CIDR 설정
- Routing PostgreSQL `verify-full`, migration/restore drill
- secret rotation, backup, alert, cost budget, rollback evidence
- immutable image/artifact provenance와 GCS object generation/hash 검증

## 6. 롤백

애플리케이션은 직전 검증 image digest/tag와 Compose revision으로 되돌린다.
데이터 변경은 사전 backup/restore 절차를 따른다. 다른 cloud stack으로의 전환은
지원되는 롤백 수단이 아니다.
