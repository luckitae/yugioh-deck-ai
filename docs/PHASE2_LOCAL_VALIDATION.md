# Phase 2 제출본 로컬 검증 기록

검증일: 2026-09-14. 이 문서는 작성 환경에서 실제 수행한 검사만 ‘통과’로 기록한다.

## 수행한 검사

| 검사 | 결과 | 해석 |
|---|---|---|
| C++17 단위 검사 빌드 | 통과 | `-Wall -Wextra -Werror -pedantic`, SQLite 링크 |
| 단위 검사 | 75개 통과 | 임시 SQLite, YDK, 응답, 스크립트 경로·오류 검사. `OCG_LoadScript`는 모의 함수 |
| AddressSanitizer + UndefinedBehaviorSanitizer | 같은 75개 통과 | 검사한 경로에서 sanitizer 오류 없음. 일반적 무결함 보증은 아님 |
| `phase2_smoke.cpp` 문법/타입 검사 | 통과 | 제공된 API 11.0 헤더 사용, `-fsyntax-only` |
| 실제 CLI `--validate-only` | 23개 통과 | 합성 SQLite에 Main 39~61장 입력. 40~60장은 validated, 39/61장은 input_error. 모든 winner/reason은 null |
| CLI의 엔진 호출 여부 | 호출 없음 | 검사 전용 스텁은 엔진 API가 호출되면 즉시 중단하도록 구성. 듀얼이나 Lua 실행을 흉내 내서 통과시키지 않음 |
| Python 두 파일 문법 | 통과 | `py_compile` |
| Workflow YAML와 shell 구문 | 통과 | YAML 구조 읽기, 각 run 블록 `bash -n` |
| 단위 검사/실제 실행 파일 분리 | 확인 | 실제 실행 파일의 링크 목록에 모의 함수가 든 `phase2_unit.cpp`가 없음 |

확인한 단위 검사 출력:

```text
[OCG log type=0] expected test error
PHASE2 UNIT PASS: 75 checks (Lua calls mocked)
```

첫 줄은 오류 전파 검사를 위해 의도적으로 만든 메시지다. 이 문구 하나를 실제 Lua 실행 오류로 오인하지 않는다. 실제 통합 실행에서 발생한 별도의 OCG 오류는 정상으로 취급하지 않는다.

확인한 CLI 검사 요약:

```text
PASS: 23 CLI checks (synthetic DB, validation only, engine calls forbidden).
```

## 아직 수행하지 않은 검사

- 원격 BabelCDB `cards.cdb` 전체를 새 로더로 읽는 실제 실행.
- 원격 CardScripts와 첨부 코어 commit을 사용한 진짜 Lua 로딩/효과 해결.
- Phase 2 실행 파일을 실제 OCGCore 공유 라이브러리에 링크한 실행.
- 새 workflow를 사용한 GitHub Actions 빌드와 39개 통합 검사.
- 이번 작성 환경에서의 Phase 1 실제 듀얼 재실행. 대신 기존 소스를 수정하지 않고 Actions 회귀 단계에 그대로 유지했다.

네트워크 다운로드 제약과 필요한 Lua 원본 부재 때문에 위 실행을 이 환경에서 수행하지 못했다. 코드를 작성하고 검사 명령을 추가한 사실은 실제 엔진 통과의 증거가 아니다.

## 코드 보존 확인

제출 패키지 작성 시 원본 ZIP의 `test/engine_test.cpp`, `test/message_decoder.cpp`, `test/message_decoder.h`와 작업본을 바이트 단위로 대조했다. 세 파일은 패키지에 넣지 않는다. 별도 `ygopro-core.git`에도 변경 파일을 제출하지 않는다.

## 다음 확인

파일 일괄 적용 → `lg2` commit/push 1회 → GitHub Actions의 첫 실패 단계 또는 최종 통과 요약과 `phase2-test-results`를 확인한다. 실제 실행 결과가 있어야 다음 호환성 판정을 확정한다.
