# Phase 5-A — 제약 보존 GA + 저비용 Prescreen

기준일: 2026-09-15

## 목적

Phase 4가 만든 100개 초기 덱을 바로 수천 판씩 듀얼시키기 전에, 구조 제약을 보존하는 탐색 연산과 저비용 선별 단계를 먼저 만든다.

이번 단계는 **실제 승률 최적화가 아니다.** `phase5-lowcost-v1` 점수는 다음 두 값만 사용한다.

1. Main Deck의 각 필수 카드를 첫 5장에서 볼 확률의 평균(70%)
2. Phase 3 후보 관계 점수의 정규화 평균(30%)

둘 다 휴리스틱이며 카드 효과의 실제 강도·콤보 성공률·매치업 승률을 증명하지 않는다. 출력에는 항상 `duel_evaluated=false`, `win_rate_evaluated=false`, `fitness_kind=low-cost-prescreen-not-winrate`를 기록한다.

## GA 구조

기본 설정은 Phase 4의 100개 중 48개를 탐색 population으로 사용하고 4세대, elite 8개, tournament 4개로 실행한다.

지원 mutation:

- `replace_card`: 보호되지 않은 Main 카드 1장 교체
- `copy_up`: 기존 카드 매수 +1, Main 총량 증가
- `copy_down`: 기존 카드 매수 -1, Main 총량 감소
- `pool_rebalance`: ENGINE ↔ GENERIC 교체
- `package_add`: Package + dependency 최소 매수 추가
- `package_remove`: root package 제거 후 더 이상 필요하지 않은 멤버 정리

모든 child는 다음 검사를 다시 통과해야 population에 들어간다.

- Main 40~60
- Extra/Side 0~15
- 필수 카드/최소 매수
- alias 합산 매수 제한
- 현재 rules profile 제한
- Main/Extra 구역
- 선택 Package 및 dependency 최소 매수
- candidate pool 밖 카드 금지
- deck identity 중복 제거

Elite는 그대로 보존하므로 같은 prescreen 점수 기준 최상위 점수는 세대가 진행되며 감소하지 않아야 한다.

## 입력

- Phase 2 DB: `data/vendor/BabelCDB/cards.cdb`
- Phase 3 candidate pool JSON
- Phase 4 population directory (`population.json`, `packages.json`, `decks/`)
- Phase 4 rules profile
- `data/search/phase5-lowcost-v1.json`

Phase 4 manifest의 DB/rules/candidate pool SHA-256이 현재 입력과 다르면 실행을 거절한다. 오래된 population을 다른 DB/후보 풀에 섞지 않는다.

## 출력

`search.json`, `SUMMARY.txt`, 최종 48개 `.ydk`를 저장한다. `search.json`은 세대별 best/mean/worst prescreen 점수, mutation별 채택 수, 실패 횟수, parent deck id를 기록한다.

## 다음 단계 — Phase 5-B

이 단계의 결과를 최종 덱으로 사용하지 않는다. 다음 구현은 범용 Duel Runner와 legal-response Bot을 만들어 실제 OCGCore 듀얼을 반복하고 다음을 기록한다.

- seed
- 선/후공
- winner/reason
- turn count
- deck id
- protocol/resource error

그 뒤 저비용 prescreen은 비싼 듀얼의 **전처리**로만 남기고, 실제 승률을 최우선 Fitness로 연결한다.
