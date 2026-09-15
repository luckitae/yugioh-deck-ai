# Phase 5 로컬 검증 범위

기준일: 2026-09-15

## Phase 5-A 기존 기준

사용자 GitHub Actions에서 다음 게이트가 통과했다.

```text
PHASE5-A SUITE PASS: 48-deck GA prescreen, deterministic repeat, seed sensitivity, constraints, C++ validation; 0 duels
```

## Phase 5-B 이 제출본에서 실행한 검사

### 1. legal-response 단위 검사

고정 OCGCore 헤더를 사용해 `-Wall -Wextra -Werror -pedantic`로 빌드 후 실행했다.

결과:

```text
PHASE5-B UNIT PASS: 27 checks
```

검사에는 Idle/Battle, yes/no, option, chain, card, place, position, tribute, counter, sum, unselect, sort, race/attribute/number, RPS와 malformed/unsupported 거절이 포함된다.

### 2. Duel Runner 컴파일

`tools/phase5_duel.cpp`와 새 response 코드를 `-Wall -Wextra -Werror -pedantic`로 컴파일했다.

### 3. 제공된 고정 OCGCore 소스로 실제 엔진 실행

첨부된 OCGCore commit 소스를 Linux에서 직접 빌드하여 synthetic DB의 서로 다른 일반 몬스터 40장 덱 두 개를 실제 엔진에서 듀얼시켰다. 카드별 효과 script가 필요하지 않는 fixture이므로 common Lua는 최소 유효 stub을 사용했다.

실측 예:

```text
PHASE5-B DUEL PASS: winner=0 reason=1 turns=15 selections=413
```

- process calls: 783
- selections: 413
- normal summons: 15
- attacks: 14
- damage events: 7
- engine errors: 0
- `MSG_RETRY`: 없음
- JSON result + JSONL trace 생성 확인

이는 runner/message-response loop의 실제 OCGCore 실행 검증이다. **실제 ProjectIgnis CardScripts 효과 덱 검증은 아니다.**

## GitHub Actions에서 추가 확인할 범위

`tools/run_phase5b_tests.py`가 이미 Phase 2에서 받은 pinned BabelCDB/CardScripts와 Phase 5-A 실제 결과를 사용한다.

- Phase 5-A 상위 2개 YDK
- seed 1/42
- candidate 양쪽 좌석
- 총 8 real OCGCore duels
- 모든 duel `finished`
- winner/reason/turn/selection 확인
- engine Lua error 0
- trace 파일 생성

최종 기대 문구:

```text
PHASE5-B SUITE PASS: 8 real OCGCore duels, 2 prescreened decks x 2 seeds x both seats, traces recorded
```

## 아직 검증하지 않은 것

- 일반적인/경쟁력 있는 상대 덱 Pool
- 강한 플레이 AI
- 여러 매치업 기반 실제 Fitness 승률
- 공식 특정 날짜 OCG/TCG 금제 인증
- Phase 5-B fixture 승률을 최종 성능으로 해석하는 것

따라서 Phase 5-B 성공 후 다음 작업은 Duel Runner를 반복 평가/GA Fitness에 연결하는 Phase 5-C다.
