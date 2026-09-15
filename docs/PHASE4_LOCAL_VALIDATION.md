# Phase 4 1차 제출 — 검증 결과와 경계

## 사용자 제공 통합 기준

- Phase 2: `PHASE2 SUITE PASS: 39 checks, 8 real-engine duels`.
- Phase 3: `PHASE3 SUITE PASS: deterministic candidate pools, explanations, limits, and rejection checks`.

위 두 결과는 사용자가 제공한 Actions 출력이다. 이번 작업에서 원격 Actions를 대신 재실행한 것은 아니다.
원격 저장소 Workflow를 읽어 기존 단계가 제출된 Phase 3 기준과 맞는지 확인했다. 원격 쓰기/commit/push는 하지 않았다.

## 이번 작성 환경에서 실행한 검사

| 검사 | 결과/범위 |
|---|---|
| Phase 4 Python 단위 검사 | **36 tests 통과**, 합성 SQLite DB. 테스트 helper가 직접 계수한 생성 항목 573개 외 별도 whitelist/Extra/CLI 시험 포함 |
| Python 구문 검사 | 새 모듈·CLI·suite·설치 검사·단위 검사 통과 |
| Phase 4 C++ validator 빌드 | C++17, `-Wall -Wextra -Werror -pedantic` 통과 |
| 기존 Phase 2 단위 검사 | **75 checks 통과**. Lua 호출은 기존 모의 함수 |
| 기존 Phase 3 단위 검사 | **41 checks 통과**. 합성 DB |
| 전체 파이프라인 모의 통합 | 실제 Phase 3 분석 실행 파일 → 새 생성기 → 기존 C++ 로더를 **합성 DB**로 실행. 기본 100개 + 복수 필수 21개 + 필수 Extra 21개 + 제한 프로필 21개 + 강제 패키지 21개 검사 |
| 생성물 재현성 | 합성 DB 기본 100개 집단을 같은 입력으로 다시 만들어 YDK/manifest/패키지/요약 파일 전체 바이트 일치 |
| C++ 교차 검사 | 위 **184개 덱** 전체 통과. 실제 듀얼 실행 아님 |
| AddressSanitizer / UndefinedBehaviorSanitizer | 새 validator를 sanitizer로 컴파일해 합성 DB 184개 덱 검사, 종료 코드 0 |
| C++ 거절 검사 | Main 39장, alias 합산 4장, 잘못된 Main/Extra 구역, 미등록 ID 거절 확인 |
| 기존 소스 보존 | Phase 1/2/3 구현 및 데이터 lock을 바이트 단위 비교. Workflow/README/.gitignore만 갱신 |
| 설치/배포 | 설치 manifest SHA 검사, ZIP 무결성 및 깨끗한 Phase 3 기준본에 추출 적용 확인 |

### 합성 DB 모의 통합과 실제 데이터 게이트를 혼동하지 않는다

로컬 통합 검사에서는 테스트 프로그램이 사용하는 실제 형식의 카드 ID 인자를 유지하되,
DB 내용을 합성 fixture로 바꿔 분석→생성→교차 검증 연결 자체를 시험했다.
해당 로컬 출력에 suite 통과 문구가 있어도 **고정 BabelCDB 검사가 통과했다는 의미가 아니다.**
합성 fixture의 카드 이름·효과 문자열은 실카드 내용이 아니다. 로컬 시험용 DB/덱은 업데이트 ZIP에 넣지 않았다.

## 이번에 확인하지 못한 것

작성 환경에서 `raw.githubusercontent.com` 호스트 이름 해석에 실패하여 고정 BabelCDB를 다운로드하지 못했다.
따라서 **이번 Phase 4의 실제 고정 DB 통합 검사는 아직 미검증**이며 적용 후 Actions에서 확인해야 한다.
다운로드 실패를 원격 DB 파일의 부재나 사용자 환경 오류로 단정하지 않는다.

생성된 효과 카드 덱을 OCGCore로 실제 플레이시키지 않았다. 승률, 플레이 강도, 소환 가능한 Extra,
실제 콤보 성립, 공식 날짜별 금제·지역 발매 합법성은 이 제출의 검증 대상이 아니다.

## Actions에 추가한 실제 데이터 검사

기존 고정 DB와 Phase 3 analyzer를 이용해 후보 풀을 생성한다.
기본 100개 집단은 Main 40..60 전체 포함, 필수 Main 최소 2장, 중복 제거,
허용 후보 범위, 프로필/패키지 제약, `.ydk`/JSON 일치를 확인한다.
같은 입력으로 재생성하여 모든 결과 파일 해시를 비교한다.
복수 필수 카드, 필수 Extra, 0/1/2장 제한+Side, 강제 패키지는 각각 21개 덱을 추가 검사한다.
총 184개를 기존 Phase 2 C++ Deck Loader로 교차 검사한다.
거절 시험은 필수 카드 금지/4장, 오래된 후보 풀, 39/61장, Extra 16장, 없는 패키지, 후보 용량 부족이다.

기대되는 통합 게이트 문구:

```text
PHASE4 SUITE PASS: 100 unique decks, 40..60 coverage, deterministic output, rules, packages, C++ validation
```

## 배포 범위

변경/추가 파일만 포함한다. `.git`, DB, CardScripts, 코어 소스, 빌드 산출물, 가상환경,
로컬 합성 시험 덱은 포함하지 않는다. 별도 `ygopro-core.git` 교체는 없다.
