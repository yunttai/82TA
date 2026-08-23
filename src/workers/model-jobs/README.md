# Model Jobs

ETA·Seat Risk 모델의 dataset snapshot, 학습, calibration, 평가, model registry 등록을 담당한다. 자동 ACTIVE 전환은 금지한다.

## Offline-verifiable entry points

- `evaluation.py`: ETA MAE/median/P90 error and interval coverage; Seat PR-AUC,
  Brier, ECE/reliability, precision/recall; route/time/sequence slice evaluation;
  conformal/quantile utilities and Platt/isotonic-compatible calibrator ports.
- `artifact_bundle.py`: exact feature schema and SHA-256 verification for native model,
  calibration, feature schema, and model card files. Pickle is never accepted.
- `registry.py`: immutable REGISTERED→VALIDATED→SHADOW→CANARY→ACTIVE→RETIRED or
  REJECTED transitions, traffic constraints, rollback planning and hashed prediction
  audit records.
- `drift.py`: delayed-label coverage and sample-size-aware numeric drift evidence.
- `routing_worker.model_jobs.lightgbm_adapter`: optional, explicit opt-in native
  LightGBM training adapter. It uses the same versioned numeric/categorical encoder
  as serving. ETA accepts non-negative scalar regression labels; Seat accepts only
  ordinal class labels 0..3 with `multiclass / num_class=4`. Dependency presence
  never means production approval and training cannot run without supplied data.
- `routing_worker.native_lightgbm`: concrete, inert-on-import serving loaders for
  verified native text artifacts and strict family-specific calibration JSON. ETA
  CONFORMAL and Seat four-class cumulative probabilities are supported; unsupported
  model shapes/methods remain unavailable rather than fabricated.
  Serving imports the same packaged `PlattCalibrator` and stepwise
  `IsotonicCalibrator` used by evaluation; the latter uses bounded (maximum 1,024)
  knots and binary lookup. Nullable ordinal-label selection excludes unobserved
  future targets instead of converting them to class zero.

No trained or calibrated model is included. Activation requires real leakage-safe
datasets, quality gates, validation evidence, security review, and operator approval.
ETA and Seat Risk metadata now append the independently versioned Bus-core context
component to the unchanged family-specific core feature order. The full worker schema
version includes the exact serving-context version, so legacy or cross-family context
metadata fails exact inference artifact verification rather than being coerced.

Durable persistence lives in `../routing_worker/repositories.py`. It stores only the
canonical lifecycle states, binds deployment interval closure to transitions, requires
ETA/Seat-specific schemas plus dataset/calibration/model-card hashes and the temporal
trip split policy, and performs rollback in one serializable transaction.
Offline model jobs retain `ETA|SEAT_RISK` training labels, expose their exact
`BUS_ETA|SEAT_RISK` persistence purpose, and use only lowercase `dev|staging|prod`
deployment identities. Uppercase runtime environments are not registry keys.

The canonical implementations are packaged under `routing_worker.model_jobs`; files
beside this README are compatibility shims and repository-local tests only.
