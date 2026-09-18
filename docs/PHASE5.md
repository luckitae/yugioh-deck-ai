# Phase 5 — 탐색과 실제 듀얼 평가

기준일: 2026-09-18

## Phase 5-A — 제약 보존 GA + 저비용 Prescreen

Phase 4의 초기 population을 실제 듀얼 전에 싸게 줄이는 단계다.

`phase5-lowcost-v1`은 필수 카드 첫 5장 접근성과 Phase 3 관계 점수를 사용하는 deterministic prescreen이다. **승률이 아니다.**

지원 mutation:

- `replace_card`
- `copy_up`
- `copy_down`
- `pool_rebalance`
- `package_add`
- `package_remove`

모든 child는 Main 40~60, Extra/Side 0~15, 필수 카드/최소 매수, alias 합산 매수, rules profile, Main/Extra 구역, Package dependency/minimum, candidate pool membership을 다시 검사한다.

사용자 GitHub Actions 기준 Phase 5-A 통합 게이트는 통과했다.

## Phase 5-B — 실제 OCGCore Duel Runner

`phase5_duel`은 pinned OCGCore 11.0 + pinned DB/CardScripts에서 두 YDK를 실제로 플레이한다. `first-legal-v1`은 강한 AI가 아니라 엔진이 요구하는 선택에 deterministic한 합법 response를 만드는 baseline이다.

주요 지원 prompt는 Idle/Battle, yes/no, option, chain, card, place, position, tribute, counter, sum, sort, race/attribute/number/card announce 등이다. 지원하지 않는 prompt나 malformed payload에는 임의 bytes를 보내지 않고 실패한다. `MSG_RETRY`도 실패다.

결과 JSON에는 winner/reason, turn/process/selection 수, summon/special summon/attack/chain/damage, prompt/action 집계, DB/script 오류 수를 기록한다. JSONL trace에는 각 선택과 주요 이벤트를 남긴다.

Phase 5-C부터 runner는 Main 필수 카드뿐 아니라 `--required-extra0/1`로 Extra 필수 카드 최소 매수도 직접 검사한다. 또한 `first_player=0`, 두 입력 deck file을 결과 provenance에 기록한다.

사용자 GitHub Actions 기준 Phase 5-B의 8 real OCGCore duel 게이트도 통과했다.

## Phase 5-C — 실제 승률 Fitness + 상대 Pool split

### 목표

저비용 점수가 아니라 **실제 OCGCore 승률을 GA의 1순위 Fitness로 연결**한다.

```text
Phase 5-A 상위 덱
        │
        ▼
constraint-preserving GA mutation
        │
        ▼
 candidate × opponent × seed × seat
        │
        ▼
 phase5_duel / first-legal-v1
        │
        ▼
 actual win rate
        │
        └── score_ppm = win_rate_ppm
```

### 상대 Pool 형식

상대 manifest는 다음 split을 명시한다.

- `training`: GA Fitness에 사용
- `validation`: 후보 선택 후 held-out 검증
- `final`: 최종 대규모 검증

한 실행에서는 **하나의 split만** 선택한다. training 평가에 validation/final 상대가 섞이지 않게 parser에서 분리한다.

지원 manifest kind:

- `test-only`: CI/기능 검증용
- `custom`: 사용자 정의
- `pinned-snapshot`: 버전이 고정된 외부/실전 상대 snapshot용

상대 YDK는 현재 rules profile로 다시 구조 검증한다. 출력에는 opponent manifest와 각 선택된 YDK의 SHA-256, Phase 2 dependency lock hash를 함께 기록한다.

### 실제 승률 집계

각 candidate는 선택된 모든 상대에 대해 각 seed, 두 좌석을 모두 플레이한다. 현재 runner에서 player 0이 선공이므로:

- candidate seat 0 = 선공
- candidate seat 1 = 후공

각 덱마다 저장:

- 전체 wins / draws / losses
- `win_rate_ppm`
- 선공/후공 별 승률
- 상대별 승률
- worst-opponent 승률
- 평균 턴 수
- 완료/실패 duel 수
- 개별 result/trace/log 경로

**Fitness의 `score_ppm`은 완전한 schedule일 때 실제 `win_rate_ppm`과 정확히 같다.** draw나 prescreen 점수를 가중해 승률보다 위에 두지 않는다.

### 오류 처리

Timeout, unsupported selection, protocol/resource/engine 오류는 승리로 치환하지 않는다.

- schedule이 전부 완료: `score_ppm = actual win_rate_ppm`
- 하나라도 실패: `score_ppm = -1`, `win_rate_evaluated = false`

따라서 실패를 이용해 높은 Fitness를 얻는 것은 불가능하다. GA는 완전 평가 덱을 항상 불완전 평가 덱보다 위에 둔다.

같은 덱은 evaluator 인스턴스 내에서 fingerprint cache를 사용해 중복 듀얼을 피한다.

### Phase 5-C CI 게이트

실제 pinned DB/CardScripts에서 상대 Pool parser와 실제 Fitness 연결을 검증한다. CI 상대는 경쟁 덱이라고 가장하지 않기 위해 명시적으로 `test-only`다.

- training: 서로 다른 일반 몬스터 40장 fixture 2개
- validation: held-out 일반 몬스터 fixture 1개
- training 실행에서 validation 상대가 사용되지 않는지 검사
- Phase 5-A 상위 3개를 실제 duel Fitness로 평가
- 1 generation GA mutation 수행
- 각 완전 평가: 2 opponents × seed 1 × 선/후공 = 4 duels
- 최종 1위의 schedule은 반드시 전부 완료
- 실제 승률로 ranking/elitism이 동작하는지 검사
- 최종 YDK를 기존 C++ validator로 재검증

예상 최종 문구:

```text
PHASE5-C SUITE PASS: actual OCGCore win-rate fitness drives 3-deck GA over 2 test-only training opponents x 1 seed x both seats; best schedule complete
```

이 CI fixture 승률은 **실제 OCGCore에서 나온 승률**이지만, 상대가 test-only이고 Bot도 baseline이므로 최종 메타 성능 수치가 아니다.

## 다음 작업

Phase 5-C가 실제 pinned 데이터에서도 통과하면 다음 우선순위는 다음과 같다.

1. **Phase 5-D: 현실적인 pinned opponent Pool** — 여러 일반/경쟁 덱 snapshot을 training/validation/final로 분리
2. `first-legal-v1`보다 강한 state-aware 정책을 추가하고 동일 덱/동일 seed A/B 비교
3. seed와 상대 수를 늘리는 staged evaluation으로 계산량 제어
4. 실제 승률 Fitness를 더 큰 GA population/generation으로 확장
5. 이후 Phase 6에서 현재 JSONL trace를 카드 사용률/전개/승리 패턴 분석으로 연결

Phase 4의 test-only rules profile은 특정 날짜 공식 OCG/TCG 금제 인증이 아니다. 공식 환경 고정은 별도 작업으로 남는다.
