# Phase 3 1차 구현 — Card Analyzer / Card Graph / Candidate Pool

기준: Phase 2 통합 검사 `PHASE2 SUITE PASS: 39 checks, 8 real-engine duels` 통과 후 적용한다.

## 목적

필수 카드 ID를 입력하면 실제 고정 `cards.cdb`의 이름·효과 텍스트·타입·카드군(setcode)·속성·종족·레벨을 분석하여 덱 생성기가 사용할 **설명 가능한 Candidate Pool**을 만든다.

이번 단계는 승률 평가가 아니다. 숫자 점수는 후보를 정렬하고 탐색 공간을 제한하기 위한 초기 휴리스틱이며, 향후 실제 듀얼 통계로 보정한다.

## 기능 feature

다음 16종을 계획서와 동일하게 사용한다.

`SEARCH, DRAW, SPECIAL_SUMMON, NORMAL_SUMMON, NEGATE, DESTROY, BANISH, RETURN, SEND_TO_GY, RECOVER, MATERIAL, TOKEN, PROTECTION, DISCARD, TRIGGER, TARGET`

현재 `phase3-text-metadata-v1`은 고정 BabelCDB의 영문 효과 텍스트를 문구 기반으로 구조화한다. 조건(IF/WHEN/WHILE/DURING), 대표 비용(PAY_LP/DISCARD/TRIBUTE/BANISH/SEND_TO_GY), 관련 zone도 함께 기록한다. 자연어 완전 해석기가 아니므로 feature 누락·과탐은 이후 Lua/실전 로그와 함께 개선한다.

## 관계

- STRONG: DB alias, 후보 텍스트가 필수 카드 이름을 직접 언급, 필수 카드가 후보 이름을 직접 언급
- MEDIUM: OCGCore와 같은 setcode 매칭 규칙, 같은 속성, 종족, 레벨, 소환 메커니즘
- WEAK: 기능 feature 중복, Monster/Spell/Trap 대분류 동일. 단, WEAK만으로는 Engine Pool에 진입시키지 않고 이미 강/중 관계로 연결된 후보의 정렬 보조에 사용
- GENERIC: 필수 카드와 강·중 관계가 없어도 SEARCH/DRAW/NEGATE/DESTROY/BANISH/PROTECTION/RECOVER 기능이 있는 카드를 별도 경로로 보존

초기 가중치는 STRONG=100, MEDIUM=20, WEAK=3이다. 기본 상한은 Engine 80, Generic 40, 전체 120이다. 이 값은 최적값이라는 뜻이 아니며 Phase 5의 실제 승률 평가 전까지 탐색 폭 관리용 고정 기준이다.

모든 후보에는 `relations[]`가 있어 **어떤 필수 카드와 어떤 관계 때문에 포함되었는지** JSON으로 추적할 수 있다.

## 프로그램별 실행

### iPad 파일 앱

`phase3_update.zip`을 `나의 iPad → a-Shell → yugioh-deck-ai`에 넣는다.

### a-Shell — 적용

```text
cd ~/Documents/yugioh-deck-ai
lg2 status
python3 -m zipfile -e phase3_update.zip .
rm phase3_update.zip
lg2 diff
```

이번 ZIP은 Phase 2가 적용된 저장소를 전제로 한다. 별도 미커밋 수정이 있다면 덮어쓰기 전에 프로젝트 폴더를 복사해 보관한다.

### a-Shell — 공통 Git 작업 한 번

```text
lg2 add .github/workflows/build.yml README.md
lg2 add src/data/card_database.h src/analysis/card_analyzer.h src/analysis/card_analyzer.cpp src/analysis/card_graph.h src/analysis/card_graph.cpp
lg2 add test/phase3_unit.cpp tools/phase3_analyze.cpp tools/run_phase3_tests.py docs/PHASE3.md docs/PHASE3_LOCAL_VALIDATION.md
lg2 status
lg2 commit -m "Add Phase 3 explainable card candidate analysis"
lg2 push
```

commit/push는 각각 한 번만 한다.

### Safari 또는 GitHub 앱 — Actions 확인

저장소 → Actions → Build → 방금 commit → `build-core`에서 기존 Phase 1/2 검사 뒤 다음을 확인한다.

```text
PHASE3 UNIT PASS: 41 checks
PHASE3 SUITE PASS: deterministic candidate pools, explanations, limits, and rejection checks
```

`phase3-test-results` artifact에는 실제 고정 DB로 만든 후보 JSON과 로그가 저장된다.

## 실제 사용자 필수 카드 분석 명령

GitHub Actions의 통합 검사는 재현성 확인용 대표 카드로 수행한다. 이후 사용자 필수 카드 ID를 분석할 때는 Linux/Actions에서 같은 `phase3_analyze` 실행 파일에 다음 형식을 사용한다.

```text
./phase3_analyze --db data/vendor/BabelCDB/cards.cdb --required 89631139 --output artifacts/my_candidates.json
```

필수 카드가 여러 장이면 `--required`를 반복한다.

```text
./phase3_analyze --db data/vendor/BabelCDB/cards.cdb --required 89631139 --required 46986414 --output artifacts/my_candidates.json
```

현재 iPad a-Shell에서 OCGCore/SQLite 개발환경을 새로 구성하는 경로로 바꾸지 않는다. 실제 분석 실행은 Actions 쪽을 정식 경로로 유지한다.

## 테스트

- 합성 DB 단위 검사 41개: 16종 중 대표 feature, 강/중/약 관계, alias, setcode, Generic Pool, 설명, 결정적 순서, 잘못된 required/limit 거절
- 실제 고정 BabelCDB: Blue-Eyes White Dragon `89631139` 1개 필수 카드, Blue-Eyes + Dark Magician `46986414` 복수 필수 카드, 작은 후보 상한, 존재하지 않는 카드 거절
- 같은 입력을 두 번 실행하여 출력 JSON SHA-256이 완전히 같은지 검사
- 후보 ID 중복, 전체 상한, 필수 카드 보존, ENGINE/GENERIC 존재, STRONG/MEDIUM 관계와 포함 이유 존재 확인

특정 날짜 OCG/TCG 금제는 아직 후보 분석 필터에 적용하지 않는다. 금제/카드풀 legality는 실제 Deck Generator가 후보를 생산하기 전에 별도 검증 계층으로 연결한다.
