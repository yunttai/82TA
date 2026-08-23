# Routing Domain

Django·ORM·HTTP·Provider raw payload에 의존하지 않는 순수 Python 도메인이다.

`routing_domain.RouteOptimizer`는 immutable `CandidateSeed`와
`LegEvaluator` port를 받아 다음을 결정적으로 수행한다.

- V1 허용 route pattern 검증과 단계별 candidate/provider-call cap
- canonical transit baseline, access/egress/upstream hub, Taxi Bridge에서 7개
  route pattern을 생성하는 `BoundedStrategyGenerator`
- coarse lower-bound pruning과 중복 제거된 exact transit/walk/taxi/mapping/
  Bus Intelligence enrichment plan
- P50/P90 leg 진입시각 기반 순차 재평가
- Bus Intelligence expected/P90 wait의 BUS leg 비용 반영
- P50/P90 transfer margin과 고정 connection feasibility
- 모든 taxi leg upper fare 합계 기반 hard budget
- 택시 배차 대기(`LegCost.wait`)와 실제 주행(`LegCost.travel`)의 분리
- constraint, topology dedupe, exact Pareto와 cycle-safe epsilon SCC 대표 정책
- FASTEST, STABLE, EFFICIENT, PUBLIC_TRANSIT_ONLY 대표 선택

전략 생성·유한 탐색 정책은 `strategy-2.0.0`, 기본 내부 ranking 정책은
`rank-0.2.0`이며 EFFICIENT는 비용순 frontier의 인접한
더 저렴한 tier 대비 successive marginal time saving을 사용한다.

Python 3.12 이상에서 독립 패키지로 설치할 수 있다.

```powershell
py -3.12 -m pip install -e src/packages/routing-domain
py -3.12 -c "import routing_domain"
```

테스트 실행:

```powershell
py -3.12 -m unittest discover -s src/packages/routing-domain/tests -v
```

`routing_domain.replay_fixtures.build_r1_r4_scenarios()`는 외부 raw fixture 없이
R1~R4 통합 replay가 사용할 canonical-domain seed를 제공한다.
