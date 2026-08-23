# ADR-0005: Provider Adapter와 Canonical Transport Model

## 상태
Accepted

## 결정
Kakao, GBIS, KMA, GITS, TMAP, ODsay raw schema를 adapter 뒤에 숨기고 domain은 canonical objects만 사용한다.

## 결과
Provider 교체·schema drift·fixture replay가 가능하다.
