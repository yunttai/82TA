# Bus Intelligence Core

차량·정류장 관측 정규화, ETA·좌석 위험 추론, boardability proxy, 기대·P90 대기시간, confidence·coverage를 구현한다.

## Domain boundary

- immutable canonical inputs only; no Provider payload or ORM object
- blocker-free `HIGH` mapping (`allows_bus_intelligence=true`) only; selected ETA P50 must be strictly after timezone-aware user arrival
- independent ETA arbitration/predictor and Seat Risk predictor ports
- target-stop future observation absence remains `None` / unobserved
- seated-bus boardability is explicitly a proxy; general-bus crowding is not seat failure
- sequential probability mass plus a conservative headway tail produces expected/P90 wait
- guarded ETA runtime arbitrates fresh official → position model → historical → unknown
- calibrated Seat Risk runtime checks serving readiness and feature-schema parity, enforces ordered probabilities, and can fall back on OOD/unavailable models
- `ACTIVE` is the only production-serving readiness; `FIXTURE_ONLY` requires explicit opt-in and never enables live capability by itself
- ETA and Seat Risk versions/readiness remain separate in result provenance

## Test

```powershell
py -3.12 -m pip install -e src/packages/bus-intelligence-core
py -3.12 -B -m pytest -p no:cacheprovider src/packages/bus-intelligence-core
```
