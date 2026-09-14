# Phase 2 1차 구현 — 적용 및 실행 안내

작성일: 2026-09-14. 기준: 첨부 `yugioh-deck-ai(2).zip`과 `ygopro-core.git(2).zip`.

## 1. 이번에 할 일

기존 프로젝트에 이번 변경 파일을 한 번에 적용하고, 한 번만 commit/push한다. 그러면 GitHub Actions가 기존 합성 덱 회귀 검사와 새 DB/Lua/실제 카드 검사를 순서대로 실행한다.

현재 작업 흐름을 바꾸지 않는다. iPad에서 엔진을 다시 설치하거나 clang·Meson·SQLite를 설치할 필요가 없다. `ygopro-core.git` 폴더도 교체하지 않는다. 제3자 데이터 저장소를 iPad에서 수동으로 내려받지 않는다.

## 2. 프로그램별 실행 순서

### 2-1. 파일 앱 — 수정본 저장

`phase2_update.zip`을 **나의 iPad → a-Shell → yugioh-deck-ai**에 저장한다. 최종 위치는 `~/Documents/yugioh-deck-ai/phase2_update.zip`이다.

압축파일에는 프로젝트 루트를 기준으로 한 상대 경로가 들어 있다. 숨김 폴더 `.github`까지 함께 적용하기 위해 파일 앱에서 풀어 옮기기보다는 다음 Python 명령으로 프로젝트 루트에 직접 푼다. 파일을 여러 번 저장해 이름 뒤에 숫자가 붙었다면 파일 앱에서 `phase2_update.zip`으로 이름을 맞춘다.

### 2-2. a-Shell — 확인 후 일괄 적용

다음 명령을 **한 줄씩** 실행한다.

```text
cd ~/Documents/yugioh-deck-ai
lg2 status
python3 -m zipfile -e phase2_update.zip .
lg2 diff
```

첫 `lg2 status`는 아직 commit하지 않은 별도 수정이 있는지 확인하는 단계다. 이번 파일과 겹치는 별도 수정이 있다면 먼저 파일 앱으로 프로젝트 폴더를 복사해 보관한다. 이번 압축 해제는 같은 경로의 파일을 덮어쓴다. `.git`과 기존 Phase 1 테스트 소스는 압축파일에 없으므로 교체하지 않는다.

`lg2 diff`에는 이미 추적 중인 workflow·`.gitignore`·README 변경이 보인다. 신규 소스는 아직 추적 전이므로 diff에 전부 표시되지 않는 것이 정상이다.

### 2-3. a-Shell — 공통 업로드를 한 번만 수행

```text
lg2 add .github/workflows/build.yml .gitignore README.md
lg2 add src/data/card_database.h src/data/card_database.cpp src/data/deck_loader.h src/data/deck_loader.cpp
lg2 add src/data/script_loader.h src/data/script_loader.cpp src/protocol/smoke_response.h src/protocol/smoke_response.cpp
lg2 add test/phase2_smoke.cpp test/phase2_unit.cpp data/phase2.lock.json
lg2 add tools/fetch_phase2_data.py tools/run_phase2_tests.py docs/PHASE2.md docs/PHASE2_LOCAL_VALIDATION.md
lg2 status
lg2 commit -m "Start Phase 2 real card data and Lua integration"
lg2 push
```

여러 `add`는 파일 목록만 나눠 입력하는 것이며, commit과 push는 각각 한 번이다. 기존 upstream 설정을 사용하므로 `lg2 push origin master`로 바꾸지 않는다. `git` 명령도 사용하지 않는다.

상태에서 새로 내려받는 `data/vendor/`나 실행 결과 `artifacts/`, ZIP, 실행 파일은 commit 대상으로 잡히지 않아야 한다. 다운로드한 인계 문서 등 다른 사용자 파일은 위의 명시적 `add` 목록에 포함되지 않는다.

### 2-4. Safari 또는 GitHub 앱 — 실제 실행 확인

`luckitae/yugioh-deck-ai` 저장소 → **Actions → Build → 방금 올린 commit → build-core**를 연다.

| 단계 이름 | 하는 일 | 통과 확인 |
|---|---|---|
| Run engine test | 기존 합성 카드 듀얼 회귀 검사 | `Duel finished by MSG_WIN` |
| Run Phase 2 unit tests | 임시 SQLite·메시지·로더 검사 | `PHASE2 UNIT PASS: 75 checks (Lua calls mocked)` |
| Fetch pinned Phase 2 data | 고정 DB/Lua를 CI에서 자동 다운로드 | `PHASE2 DATA READY` |
| Build Phase 2 real-data test | 실제 OCGCore·SQLite를 새 실행 파일에 연결 | 컴파일 단계 성공 |
| Run Phase 2 real-data tests | 실제 데이터 검증, 듀얼, 효과/오류 검사 | `PHASE2 SUITE PASS: 39 checks, 8 real-engine duels` |
| Upload test results | 성공/실패 로그 보관 | `phase2-test-results` artifact 생성 |

위 문구는 **앞으로 실행했을 때의 기대 결과**이며, 이 제출에서 실제 원격 통합 검사가 이미 통과했다는 뜻은 아니다.

### 2-5. 결과 전달 — 다음 개발의 입력

성공하면 `Run Phase 2 real-data tests` 마지막 출력과 `phase2-test-results`를 전달한다. 실패하면 **처음 빨갛게 실패한 단계**의 로그와 같은 artifact를 전달한다. 원인이 소스 문제인지, 데이터 호환성인지, 다운로드/환경 문제인지 분리할 수 있다. 실행 실패를 승패 결과로 사용하지 않는다.

## 3. 추가한 코드

| 파일 | 역할 |
|---|---|
| `src/data/card_database.h/.cpp` | CDB 전체를 읽기 전용으로 로드하고 CardReader에 제공한다. race 64비트, setcodes 16비트 배열·0 종료·수명, Link marker와 Pendulum scale을 변환한다. |
| `src/data/deck_loader.h/.cpp` | `.ydk` Main/Extra/Side 분리, 카드 존재·구역·매수·필수 Main 카드 조건을 검사한다. |
| `src/data/script_loader.h/.cpp` | 공통/카드 Lua 읽기·캐시·재귀 의존, 엔진 로그와 오류 전파를 담당한다. |
| `src/protocol/smoke_response.h/.cpp` | 시험 정책용 IDLE/CHAIN/CARD/PLACE 응답과 범위 검사를 담당한다. |
| `test/phase2_unit.cpp` | SQLite 임시 fixture·응답 인코더·Lua 호출 모의 단위 검사다. |
| `test/phase2_smoke.cpp` | 실제 데이터로 덱을 넣고, 정상 WIN 또는 오류를 JSON으로 남기는 별도 실행 파일이다. |
| `tools/fetch_phase2_data.py` | 고정 commit 원본을 받고 실제 SHA·DB 해시·Lua 파일별 해시를 기록한다. CI 전용이다. |
| `tools/run_phase2_tests.py` | 실제 DB로 YDK fixture를 만들고 정상/실패 통합 검사를 실행한다. CI 전용이다. |
| `data/phase2.lock.json` | 코어·DB·스크립트·시험 룰의 버전 기준이다. |
| `.github/workflows/build.yml` | 공통 설치·빌드·테스트·artifact 업로드를 한 번의 push에 묶는다. |

`test/engine_test.cpp`, `test/message_decoder.cpp`, `test/message_decoder.h`는 원본 그대로다. `ygopro-core.git`도 수정하지 않았다.

## 4. 데이터와 룰 기준

현재 코어 날짜에 맞춘 **2026-09-03 snapshot**을 선택했다. 최신 데이터라는 뜻이나 모든 카드 호환성을 검증했다는 뜻은 아니다.

| 대상 | 원본 | 고정 commit |
|---|---|---|
| OCGCore API 11.0 | `https://github.com/edo9300/ygopro-core` | `b8c05dff14da0b13608950a73906287dc0b601f9` |
| 카드 DB | `https://github.com/ProjectIgnis/BabelCDB` | `3db9b2e5b048e1bf7ae6f1af39f2d185d91c07c5` |
| 카드 Lua | `https://github.com/ProjectIgnis/CardScripts` | `c4faac1c5d75929f6f54751117952c074bddf7e8` |

룰 프로필은 `mr5-no-banlist-smoke-v1`이다. OCGCore의 `DUEL_MODE_MR5`, LP 8000, 초기 패 5장, 드로우 1장, 선공 플레이어 0을 사용한다. seed 배열은 `[입력 seed, 2, 3, 4]`이다.

Main 40~60장, Extra/Side 각 0~15장, DB alias 기준 Main+Extra+Side 합산 최대 3장을 검사한다. DB의 `ot & 3`인 카드만 허용하므로 OCG 또는 TCG 범위의 카드를 쓰는 시험 프로필이다. 특정 한 지역의 대회 카드풀이나 실제 금제를 보증하지 않는다. 토큰·Main/Extra 잘못된 배치·없는 카드·잘못된 ID는 거절한다.

`--required-main 46130346=3`처럼 필수 카드의 정확한 ID와 최소 매수를 입력할 수 있다. 현재 이 조건은 플레이어 0의 Main에만 적용된다. Side는 조건을 만족시키지 않는다. 별도 일러스트 ID를 자동으로 필수 카드와 동일시하지 않는다.

## 5. 실제 통합 검사 구성

실제 원격 데이터 확보와 네이티브 빌드가 성공하면 다음을 실행한다.

**입력 22건:** Main 40부터 60까지 21개 크기 전부와 필수 카드 포함 조건 1건.

**듀얼 8건:** 일반 몬스터 40장, 일반 몬스터 60장, Main 40장+Extra 1장+Side 1장, Hinotama 3장 포함 40장 덱을 각각 seed 1과 42로 실행한다. 각 듀얼은 같은 fixture를 두 플레이어에게 넣는다. 이것은 환경 검증용이며 승률 평가용 실험 설계가 아니다.

**오류 9건:** 39장, 61장, 4장 중복, 미등록 카드, 없는 DB, 필수 카드 없음, 정책 미지원 카드, 공통 Lua 없음, 효과 Lua 없음.

일반 몬스터 후보는 실제 DB에서 `type=17`, `alias=0`, `ot&3` 조건으로 ID 오름차순으로 가져오고 카드마다 최대 3장씩 넣는다. 수작업으로 추측한 카드 정보나 합성 DB로 대체하지 않는다. Extra 투입 검사는 실제 DB의 비효과 융합 몬스터 중 대응 Lua가 있는 카드를 선택한다. **Extra 소환은 하지 않고 로딩·투입 수만 검사한다.** Side는 듀얼에 넣지 않는다.

효과 카드는 **Hinotama, ID `46130346`**이다. 단순 효과 카드로서 패에 있을 때 발동하고 상대에게 500 효과 데미지를 준다. 검사는 해당 Lua가 로드되었는지, 실제 발동 응답이 있었는지, 체인 해결과 500 데미지 메시지가 있었는지, 오류 없이 `MSG_WIN`에 도달했는지를 함께 확인한다. 단순히 덱에 효과 카드를 넣고 끝까지 패스한 결과는 통과시키지 않는다.

통합 검사의 정책은 이 fixture만을 위한 제한 정책이다. 일반 소환·전투·임의 효과 선택을 잘하는 AI가 아니다. `--validate-only`는 다른 덱도 구조 검사할 수 있지만, 실제 듀얼 정책은 지정한 일반 몬스터/Hinotama Main만 지원한다. 미지원 선택은 임의 응답하지 않고 중단한다.

## 6. 오류 처리와 결과 파일

`artifacts/phase2_suite.json`은 검사별 명령·기대 상태·실제 상태·YDK SHA-256을 기록한다. 각 검사에는 별도 `.json`과 `.log`가 있다. 데이터 식별은 `data_manifest.json`, 시험 카드 이름과 덱 해시는 `fixture_manifest.json`에 있다. 전체 Lua 및 DB 자체는 artifact에 넣지 않는다.

정상 완료는 `finished`와 winner/reason으로 표시한다. 덱 검증만 하면 `validated`이며 승패는 null이다. 그 밖의 입력 오류, 자료 오류, 프로토콜 오류, 미지원 선택, WIN 없는 종료, 한도 초과, 효과 미실행은 별도 상태로 남기고 winner/reason을 null로 만든다. Python의 실행 시간 초과도 패배가 아니라 검사 실패다.

없는 효과 Lua를 정상 카드처럼 흉내 내지 않는다. 정상적인 일반 몬스터의 미제공 Lua 및 엔진 내부 임시 카드 `c0.lua`만 예외적으로 누락될 수 있다. 일반 Pendulum 몬스터의 스크립트는 필수다. 공통 helper인 `unofficial/proc_unofficial.lua`는 utility 의존 때문에 읽지만, `c<ID>.lua`를 unofficial/pre-errata 카드로 조용히 대체하지 않는다.

경로 `..`와 스크립트 루트 밖으로 나가는 심볼릭 링크를 거절한다. Lua의 unsafe libraries는 활성화하지 않는다. 엔진 오류 로그는 첫 오류를 보존하고 해당 듀얼을 실패 처리한다.

## 7. 검증 완료와 남은 항목

이번 작성 환경에서 단위 검사 75개 및 메모리 sanitizer 재검사, CLI 검증 23개, 경고를 오류로 취급한 C++ 컴파일, Python 문법 및 workflow 구문 검사를 수행했다. CLI 검사는 임시 합성 DB와 `--validate-only`만 사용했고 엔진 호출은 금지했다. 상세 구분은 `PHASE2_LOCAL_VALIDATION.md`에 있다.

**실제 원격 CDB/Lua+OCGCore 통합 실행은 이번 작성 환경에서 수행하지 못했다.** 네트워크 다운로드 제약으로 필요한 원본 데이터와 Lua 라이브러리를 모두 확보하지 못했으며, 위 Actions 검사가 그 확인 단계다. 따라서 현재 상태는 ‘Phase 2 1차 코드 제출, 원격 통합 검증 대기’다.

통합 검사 통과 후에도 실제 날짜별 금제와 카드풀, 사용자 필수 카드 입력, 추가 소환·전투·선택 경로, 범용 플레이 AI·상대 Bot·덱 탐색·승률 최적화는 별도 작업이다. 이번 패스 정책의 승패를 AI 실력이나 최적 덱의 증거로 사용하지 않는다.

## 8. 조사 근거

아래 자료는 구현 시 참고한 외부 원본이다. 첨부 코어의 ABI·프로토콜 소스와 구분한다.

- BabelCDB 고정 revision: https://github.com/ProjectIgnis/BabelCDB/tree/3db9b2e5b048e1bf7ae6f1af39f2d185d91c07c5
- CardScripts 고정 revision: https://github.com/ProjectIgnis/CardScripts/tree/c4faac1c5d75929f6f54751117952c074bddf7e8
- 공통 utility: https://github.com/ProjectIgnis/CardScripts/blob/c4faac1c5d75929f6f54751117952c074bddf7e8/utility.lua
- 공통 unofficial helper: https://github.com/ProjectIgnis/CardScripts/blob/c4faac1c5d75929f6f54751117952c074bddf7e8/unofficial/proc_unofficial.lua
- 효과 시험 원본: https://github.com/ProjectIgnis/CardScripts/blob/c4faac1c5d75929f6f54751117952c074bddf7e8/official/c46130346.lua
- CDB 변환 참고: https://github.com/edo9300/edopro/blob/master/gframe/data_manager.cpp (조사 시점의 보조 참고; 고정된 테스트 의존성은 아니다.)

제3자 저장소에는 각 원본의 라이선스가 포함되어 있다. 이번 수정 ZIP에는 제3자 DB·카드 Lua·엔진 바이너리를 재배포하지 않는다.
