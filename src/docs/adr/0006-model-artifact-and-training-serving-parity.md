# ADR-0006: 안전한 Model Artifact와 Training/Serving Parity

## 상태
Accepted

## 결정
request-supplied pickle path를 제거하고 native model, metadata, feature schema, calibration, hash, model card를 registry로 관리한다. training과 serving은 같은 feature builder를 사용한다.

## 결과
schema mismatch는 inference를 거절하고 fallback한다.
