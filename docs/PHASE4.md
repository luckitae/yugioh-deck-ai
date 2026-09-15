# Phase 4 1차 — Package / 규칙 프로필 / 초기 덱 생성

## 1. 이번 단계의 기준

사용자 CI에서 Phase 2 `39 checks, 8 real-engine duels` 및 Phase 3
`deterministic candidate pools, explanations, limits, and rejection checks`가 통과한 상태에서 적용한다.
기존 Phase 1/2/3 소스와 데이터 lock은 변경하지 않는다. 기존 Workflow에 새 검사를 추가한다.

이번 제출은 Phase 4 전체 또는 승률 AI 완성 선언이 아니다.
**후보 풀에서 조건을 만족하는 초기 덱 집단을 만드는 첫 구현**이다.

```text
Phase 3 Candidate JSON + cards.cdb + 명시적 RuleProfile + 필수 카드/매수
    → 허용 후보 / 제외 이유
    → 관계 기반 Package + 선택적 명시 Package
    → Main 40~60 / Extra / Side 초기 population
    → 구조·매수·필수 카드·패키지 재검사
    → 실제 카드 ID 기반 중복 제거
    → .ydk + population.json + packages.json
    → 기존 Phase 2 C++ Deck Loader의 독립 구조 교차 검사
```

## 2. 구현 내용

| 구성 | 동작 |
|---|---|
| `src/deck/rules.py` | DB 읽기 전용 열기, 구조/스코프/alias 합산 매수/프로필 제한/필수 조건, YDK 입출력, 덱 ID |
| `src/deck/packages.py` | Phase 3 JSON 검증·필터링, 이름 참조/카드군 기반 묶음, 명시 패키지·의존성·순환 검사 |
| `src/deck/generator.py` | seed 기반 초기 집단, 지정된 Main 크기 순환, 패키지 일괄 적용, 후보 충전, 중복·상한·시도 예산 |
| `tools/phase4_generate.py` | CLI, 입력/소스 SHA-256, YDK/manifest 저장, 실패 시 완성 population 미노출 |
| `tools/phase4_validate.cpp` | 기존 `card_database.cpp`와 `deck_loader.cpp`를 재사용하는 일괄 구조 검사 |
| `tools/check_phase4_install.py` | a-Shell에서 표준 라이브러리만으로 수정 파일 및 보존 소스의 SHA-256 확인 |

생성 로직은 Python 표준 라이브러리만 사용한다. C++/엔진 부분은 기존 빌드 경로를 유지한다.
AI 라이브러리, GPU, 새로운 iPad 컴파일 환경을 설치하지 않는다.

### 필수 카드

`--required-main 89631139=2`는 Main에 해당 **정확한 ID**를 2장 이상 넣는 조건이다.
Side나 다른 alias ID로 대신 만족시키지 않는다. 복수 카드는 옵션을 반복한다.
Extra의 필수 카드는 `--required-extra ID=매수`로 별도 지정한다.
Phase 3 JSON의 `required` ID 집합과 Generator의 필수 ID 집합이 다르면 오래된 풀로 보고 거절한다.

### 덱 크기와 매수

기본 생성량은 100개, Main 크기는 40~60 전체 21종이다. 크기 순환으로 각 크기가 최소 한 번 등장한다.
`--sizes 40,50,60`처럼 부분 범위를 지정할 수 있다. `count`가 지정 크기 종류 수보다 작으면 거절한다.
Extra는 기본적으로 허용 후보 용량 내 최대 15장까지 채운다. `--extra-size` 지정 시 정확한 크기다.
Side는 기본 0장이고, `--side-size` 지정 시 정확한 크기로 생성한다. 사이딩 전략은 구현하지 않았다.

Main/Extra/Side 합산 매수 제한은 DB alias 단위다. 그러나 **중복 덱 ID는 실제 카드 ID를 보존**한다.
alias를 공유한다고 효과까지 같다고 볼 수 없으므로 서로 다른 ID의 덱을 무조건 합치지 않는다.
각 구역 내부 정렬 순서만 정규화해 SHA-256을 계산하며, Main/Extra/Side 구분은 유지한다.

### 패키지

자동 패키지는 `MENTIONS_REQUIRED_NAME`, `NAMED_BY_REQUIRED`, `SHARED_SETCODE` 관계의 카드 쌍이다.
속성/종족/레벨이 같다는 근거만으로 의존 패키지를 만들지는 않는다. alias 쌍도 자동 패키지에서 제외한다.
이 관계들은 **휴리스틱**이다. 소환 가능성, 발동 조건, 충돌하는 제약, 콤보 성립은 아직 검증하지 않는다.

Package의 `count`는 그 패키지를 골랐을 때 지킬 **최소 매수**다.
공유되는 같은 카드의 최소 매수는 최댓값으로 합친다. 패키지마다 가산해서 중복 강제하지 않는다.
선택한 패키지의 전체 멤버와 의존성을 일괄 적용하고, 최종 덱에서도 다시 검사한다.
강제 패키지가 필수 카드·매수 제한·구역 용량과 충돌하면 조용히 제거하지 않고 실패한다.

외부 패키지 JSON은 다음 스키마를 받는다. 아래 ID는 설명용이며 사용하려는 후보 풀에 모두 있어야 한다.

```json
{
  "schema": 1,
  "packages": [
    {
      "id": "my-package",
      "members": [
        {"section": "main", "code": 89631139, "count": 2},
        {"section": "main", "code": 46986414, "count": 1}
      ],
      "requires": [],
      "evidence": "사용자가 명시한 시험용 묶음; 콤보 성립을 주장하지 않음"
    }
  ]
}
```

`--packages 파일`로 추가하고 `--force-package my-package`로 강제할 수 있다.
위 예시는 유효한 JSON 형태를 보여줄 뿐 두 카드의 전략적 시너지를 추천하는 뜻이 아니다.

### 규칙 프로필과 실제 금제의 구분

`--rules`는 필수다. 프로필 누락 시 제한 없는 기본값으로 진행하지 않는다.
배포한 `data/rules/phase4-test-no-banlist.json`은 **테스트 전용, 공식 날짜별 금제 미적용**이다.
공식 OCG/TCG 금제 날짜·지역을 사용자 대신 확정하지 않았다.

```json
{
  "schema": 1,
  "id": "custom-example-v1",
  "kind": "custom",
  "scope_mask": 3,
  "default_limit": 3,
  "limits": {"89631139": 2},
  "source": "사용자가 정한 테스트 제한; 공식 금제 아님",
  "note": "구조와 입력된 매수 제한을 검사하는 예시"
}
```

`limits`의 0/1/2/3은 금지/최대 1/2/3장을 뜻한다. 서로 같은 alias 그룹에 여러 제한이 있으면 엄격한 값을 사용한다.
`default_limit=0`은 목록에 명시되지 않은 그룹을 허용하지 않는 화이트리스트 방식이다.
`scope_mask=1/2/3`은 고정 DB의 OCG/TCG/둘 중 하나 스코프와 비교한다.
이는 **특정 지역/날짜의 실제 발매 검증을 대신하지 않는다.**
알 수 없는 프로필 필드, 중복 JSON 키, DB에 없는 제한 대상, 음수/잘못된 매수는 거절한다.
공식 LFList 파일 자동 다운로드/변환이나 최신 금제 선택은 이번 구현에 없다.

금지·제한·준제한의 합산 규칙 참고: Konami [Deck Construction Rules](https://www.yugioh-card.com/en/limited/).
구현의 타입/alias 처리 기준은 기존 고정 OCGCore 및 Phase 2 `deck_loader.cpp`다.

### 샘플링과 실패 처리

기본 후보 채우기는 ENGINE/GENERIC 구분과 Phase 3 점수를 이용하는 seed 기반 휴리스틱이다.
10/25/40%의 Generic 선택 확률을 순환하지만 실제 최종 비율을 강제하거나 최적 비율이라고 주장하지 않는다.
필수 카드는 점수 가산이 아니라 하드 제약으로 먼저 넣는다.
제약을 완화하거나 외부 카드로 몰래 보충하지 않는다. 부족한 풀은 명시적 오류로 처리한다.
중복 재시도 횟수는 `--attempts-per-deck`로 제한한다. 예산 소진은 탐색 실패이지 불가능성 증명이 아니다.

## 3. 지금 사용자 작업 — 한 번 적용하고 한 번 push

### 파일 앱

`phase4_update.zip`을 다음 위치에 ZIP 그대로 저장한다.

```text
나의 iPad → a-Shell → yugioh-deck-ai → phase4_update.zip
```

`(1)` 같은 접미사가 붙으면 `phase4_update.zip`으로 이름을 맞춘다.
별도 `ygopro-core.git` 폴더는 교체하지 않는다. GitHub 웹 편집도 하지 않는다.

### a-Shell — 아래 각 줄을 따로 실행

```sh
cd ~/Documents/yugioh-deck-ai
lg2 status
python3 -m zipfile -t phase4_update.zip
python3 -m zipfile -e phase4_update.zip .
python3 tools/check_phase4_install.py
rm phase4_update.zip
lg2 diff
```

처음 `lg2 status`에 별도 미커밋 수정이 있다면 덮어쓰기 전 파일 앱으로 폴더를 복사해 보관한다.
ZIP 검사/압축 해제/설치 검사 중 하나라도 실패하면 다음 줄로 진행하지 않는다.
**`PHASE4 INSTALL PASS` 확인 뒤 ZIP을 삭제한다.** 설치 검사는 SQLite나 C++ 컴파일을 실행하지 않는다.

### a-Shell — 공통 add/commit/push

```sh
lg2 add .github/workflows/build.yml .gitignore README.md
lg2 add src/deck/__init__.py src/deck/rules.py src/deck/packages.py src/deck/generator.py
lg2 add tools/phase4_generate.py tools/phase4_validate.cpp tools/run_phase4_tests.py tools/check_phase4_install.py
lg2 add test/phase4_unit.py data/rules/phase4-test-no-banlist.json data/phase4.install.json
lg2 add docs/PHASE4.md docs/PHASE4_LOCAL_VALIDATION.md
lg2 status
lg2 commit -m "Add Phase 4 constrained package deck generation"
lg2 push
```

commit과 push는 각각 한 번이다. `lg2 add .`나 `lg2 push origin master`로 바꾸지 않는다.

### Safari 또는 GitHub 앱 — 실행 결과

```text
luckitae/yugioh-deck-ai → Actions → Build → 방금 commit → build-core
```

기존 Phase 1/2/3 검사가 통과한 다음 다음 단계를 확인한다.

```text
Run Phase 4 unit tests
Build Phase 4 deck validator
Run Phase 4 real-data generation tests
```

기대 출력:

```text
PHASE4 UNIT PASS: 36 tests (synthetic DB; no duels)
PHASE4 SUITE PASS: 100 unique decks, 40..60 coverage, deterministic output, rules, packages, C++ validation
```

Artifacts의 `phase4-test-results`에는 기본 100개 덱, 동일 입력 반복본,
복수 필수/필수 Extra/0·1·2장 제한/강제 패키지 시험 결과와 개별 로그가 저장된다.
**이 단계에서 생성 덱을 듀얼시킨 횟수는 0이다.** Phase 2의 기존 8듀얼 회귀 검사는 별도로 그대로 돈다.

## 4. 개발자용 실제 생성 명령 (Linux/Actions)

현재 사용자가 추가 실행할 명령이 아니다. iPad에 native 실행 환경을 만들지 않는다.

```sh
./phase3_analyze --db data/vendor/BabelCDB/cards.cdb --required 89631139 --engine-limit 160 --generic-limit 100 --total-limit 280 --output artifacts/my_pool.json
python3 tools/phase4_generate.py --db data/vendor/BabelCDB/cards.cdb --pool artifacts/my_pool.json --rules data/rules/phase4-test-no-banlist.json --required-main 89631139=2 --count 100 --sizes 40:60 --seed 1 --output artifacts/my_population
```

이 명령의 카드/매수는 통합 검사용 예시이지 사용자의 최종 필수 카드 선택을 대신하지 않는다.
출력 폴더가 이미 있으면 덮어쓰지 않는다. 새 이름의 출력 폴더를 사용한다.
동일한 파일 입력·설정·Python 버전·소스에서 결과 파일을 바이트 단위로 비교할 수 있다.

`population.json`에는 규칙 원본, 필수 조건, seed·설정, DB/풀/규칙/패키지/생성 소스 해시,
후보 제외 이유, 덱 ID, 덱 목록, 선택한 패키지와 실제 ENGINE/GENERIC 채용 수를 기록한다.
`source_sha256`은 실행 코드 추적용이며 사용자 절대 경로·시각을 결과에 넣지 않는다.

## 5. 아직 하지 않은 것

실제 날짜별 공식 금제·발매 범위의 확정, 카드 텍스트의 완전한 의미 분석,
소환/콤보 성립·제약 충돌 검증, 카드/Package/매수/덱 크기 변이 API,
강한 Our Bot/Opponent Bot, 생성 덱의 듀얼 평가, 승률 최적화와 최종 플레이 가이드는 남아 있다.

다음 개발은 이 초기 집단을 제약 보존 변이와 실제 플레이 정책에 연결한다.
현재 smoke 정책에 모든 효과 카드 덱을 넣고 패스로 끝낸 승률을 최적화 결과로 사용하지 않는다.
