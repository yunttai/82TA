# ADR-0003: 두 개의 Django 배포 단위로 시작한다

## 상태
Accepted

## 결정
Public Service Backend와 Private Routing API를 별도 배포한다. Routing domain은 Django 독립 package로 유지한다.

## 대안
단일 monolith, 초기 microservices 다수.

## 결과
향후 `InProcessRoutingGateway`로 물리 통합 가능하며 Public 계약은 유지한다.
