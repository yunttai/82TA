# Docker Layout

향후 각 실행 단위의 Dockerfile·compose fragment를 이 디렉터리에 둔다.

- service-api
- routing-api
- web build
- transport-collector
- data-quality
- model-jobs

이미지는 독립 lockfile과 non-root runtime, read-only filesystem 가능한 구성을 사용한다.
