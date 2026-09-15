# Phase 5 — 탐색과 실제 듀얼 평가

기준일: 2026-09-15

## Phase 5-A — 제약 보존 GA + 저비용 Prescreen

Phase 4의 100개 초기 덱을 바로 대량 듀얼시키기 전에 구조 제약을 보존하는 mutation/search kernel을 만든 단계다.

`phase5-lowcost-v1` 점수는 필수 카드 첫 5장 접근성 70% + Phase 3 관계 점수 30%의 deterministic 정수 지표다. 승률 추정치가 아니다.

지원 mutation:

- `replace_card`
- `copy_up`
- `copy_down`
- `pool_rebalance`
- `package_add`
- `package_remove`

모든 child는 Main 40~60, Extra/Side 0~15, 필수 카드·최소 매수, alias 합산 매수, rules profile, Main/Extra 구역, Package dependency/minimum, candidate pool membership을 다시 검사한다.

## Phase 5-B — 실제 OCGCore Duel Runner

### 목적

Phase 5-A가 만든 YDK를 실제 OCGCore에 넣고 **엔진이 요구한 선택에 합법 response를 보내 한 판을 끝까지 실행**한다.

새 구성:

```text
Phase 5-A YDK
   │
   ▼
phase5_duel
   │
   ├─ OCGCore 11.0 / pinned DB / pinned CardScripts
   ├─ message_decoder
   └─ first-legal-v1 Bot
          │
          ▼
      OCG_DuelSetResponse
          │
          ▼
 winner / reason / turns / selections / action trace
```

### first-legal-v1 정책

강도 학습용 정책이 아니라 **합법성/실행 기반을 확보하기 위한 deterministic baseline**이다.

주요 동작:

- Idle: 효과 발동 → 특수 소환 → 일반 소환 → 표시 변경 → 세트 → Battle/End 순으로 진행
- Battle: 효과 발동 → 공격 → Main2/End
- Yes/No: Yes
- Option: index 0
- Chain: 가능한 첫 chain, 없으면 pass
- Card: 최소 요구 장수의 앞쪽 candidate
- Place/Position: 첫 합법 zone / 공격 표시 우선
- Tribute: release value를 만족하는 deterministic subset
- Counter: 앞 카드부터 필요한 수만큼 분배
- Sum: exact mode는 DP로 합 조건을 만족하는 subset 탐색
- Sort: 현재 순서 유지
- Race/Attribute/Number 선언: deterministic 첫 합법 선택
- Announce Card: pinned DB 전체에서 OCGCore opcode 조건을 만족하는 첫 declarable card

지원하지 않는 prompt나 malformed payload에는 임의 bytes를 보내지 않는다. `unsupported_selection` 또는 `protocol_error`로 종료한다. OCGCore의 `MSG_RETRY`도 실패다.

### Duel Runner 출력

`phase5_duel`은 JSON 결과와 선택 trace(JSONL)를 출력한다.

결과 주요 필드:

- seed
- winner / reason
- turn count / process calls
- selection count
- summon / special summon / attack / chain / damage 집계
- prompt별 횟수
- action별 횟수
- script/card-reader error 수

Trace는 각 selection의 player, prompt, action, 선택 카드 code/index와 주요 turn/attack/damage event를 기록한다. 이후 Play Analyzer의 입력으로 사용한다.

## Phase 5-B 통합 게이트

Actions에서는 Phase 5-A `search_a`의 상위 2개 실제 생성 덱을 사용한다. 상대는 고정 DB에서 고른 **서로 다른 일반 몬스터 40장 test fixture**다.

각 후보를:

- seed 1, 42
- candidate가 player 0 / player 1 양쪽 좌석

으로 실행해 총 **8 real OCGCore duels**을 요구한다.

통과 조건:

- 8판 모두 `status=finished`
- `MSG_WIN`으로 winner/reason 획득
- selection/turn 실제 발생
- Lua engine error 0
- trace 파일 생성
- 적어도 2종 이상의 selection prompt 실제 관찰

이 fixture 승률은 실제 엔진에서 계산된 값이지만 **최종 덱 Fitness가 아니다.** 상대 덱이 일반적인 경쟁 덱 Pool이 아니기 때문이다.

## 다음 단계 — Phase 5-C

1. 상대 덱 Pool 입력 형식과 고정 snapshot 확정
2. candidate × opponent × seed × 선/후공 반복 평가
3. 실패/timeout을 승리로 처리하지 않는 evaluator
4. 실제 승률을 최우선 Fitness로 연결
5. Phase 5-A prescreen은 비싼 듀얼 전처리로만 사용
6. 듀얼 trace를 Play Analyzer로 연결

특정 Bot/상대 덱 Pool의 품질이 충분한지는 Phase 5-C에서 별도 검증한다.
