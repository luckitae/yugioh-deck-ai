# Phase 5 로컬 검증 범위

기준일: 2026-09-18

## 사용자 Actions에서 이미 통과한 기준

```text
PHASE5-A SUITE PASS: 48-deck GA prescreen, deterministic repeat, seed sensitivity, constraints, C++ validation; 0 duels
PHASE5-B SUITE PASS: 8 real OCGCore duels, 2 prescreened decks x 2 seeds x both seats, traces recorded
```

따라서 Phase 5-C는 위 기능을 삭제/대체하지 않고 회귀 검사로 계속 실행한다.

## Phase 5-C 제출본에서 로컬 확인한 항목

### 1. 실제 duel Fitness 단위 검사

가짜 runner를 사용하여 OCGCore와 독립적으로 parser/집계/오류 규칙을 검사했다.

```text
PHASE5-C UNIT PASS: 34 checks (fake runner; no OCGCore duels)
```

확인 범위:

- seed parser와 중복/잘못된 seed 거절
- training/validation/final split 분리
- 상대 manifest 경로 traversal 거절
- 전체/선공/후공/상대별 W/D/L과 승률 계산
- worst-opponent 승률
- 같은 덱 평가 cache
- runner result/evaluation artifact 생성
- runner 실패가 `score_ppm=-1`이 되는지
- 불완전 평가가 `win_rate_evaluated=false`인지

### 2. Phase 5-A/B 회귀

```text
PHASE5-A UNIT PASS: 35 checks (no engine duels)
PHASE5-B UNIT PASS: 27 checks
```

Phase 5-C를 위해 `run_search(..., operations=...)` 선택 인자를 추가했지만 기본값은 기존 6개 mutation 전체이므로 Phase 5-A 동작은 유지된다.

### 3. Duel Runner 컴파일 검사

수정한 `tools/phase5_duel.cpp`를 다음 조건으로 syntax compile했다.

- C++17
- `-Wall -Wextra -Werror -pedantic`
- 제공된 고정 OCGCore headers

추가한 Extra required 검사와 provenance 필드에서 컴파일 경고/오류가 없음을 확인했다.

### 4. Phase 5-C 전체 CLI 합성 통합 검사

합성 SQLite 카드 DB, Phase 3 형식 candidate pool, Phase 4 package manifest, Phase 5-A 형식 search population, 두 상대 manifest, deterministic fake runner를 연결해 실제 CLI를 끝까지 실행했다.

실측:

```text
PHASE5-C OPTIMIZE PASS: population=3 actual_duels=20 best_win_rate_ppm=500000
```

확인:

- generation 0 + 1 실제 Fitness evaluator 연결
- mutation child 생성
- 2 opponents × 양쪽 seat 반복
- 동일 덱 cache
- 최종 `search.json`, YDK, duel evaluation/result/trace/log 생성
- `score_ppm == actual win_rate_ppm`

이 20회는 **가짜 runner 호출**이므로 실제 엔진 듀얼 수로 주장하지 않는다.

## GitHub Actions에서 새로 확인할 범위

로컬 환경에는 pinned BabelCDB/CardScripts repository를 다시 내려받을 네트워크가 없으므로 다음은 아직 검증하지 않았다.

- 실제 pinned BabelCDB/CardScripts의 Phase 5-A 상위 3개
- 실제 `phase5_duel` + OCGCore 반복 evaluator
- test-only training opponent 2개에 대한 real Fitness
- 실제 mutation child의 지원 prompt 완주 여부

Actions에서 기대하는 최종 문구:

```text
PHASE5-C SUITE PASS: actual OCGCore win-rate fitness drives 3-deck GA over 2 test-only training opponents x 1 seed x both seats; best schedule complete
```

낮은 순위 mutation child가 지원되지 않는 prompt 때문에 실패하는 것은 Fitness에서 승리로 계산되지 않는다. 통합 게이트는 최소한 최종 1위가 전체 schedule을 실제로 완료해야 통과한다.

## 아직 최종적으로 검증하지 않은 것

- 경쟁력 있는/현실적인 opponent snapshot의 품질
- `first-legal-v1`보다 강한 플레이 정책
- 여러 seed/많은 상대/대규모 population에서의 통계적 안정성
- training/validation/final을 실제 서로 다른 상대 snapshot으로 사용한 과적합 검증
- 특정 날짜 공식 OCG/TCG 금제/발매 범위 인증

따라서 Phase 5-C 성공은 **실제 승률을 GA Fitness로 연결했다는 의미**이며, 최종 덱 성능이 충분히 강하다는 의미는 아니다.
