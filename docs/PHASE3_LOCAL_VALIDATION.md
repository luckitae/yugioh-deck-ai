# Phase 3 local validation

작성 환경에서 수행한 검증과 아직 Actions에서 확인해야 하는 범위를 구분한다.

## 통과한 항목

- `clang++ -std=c++17 -Wall -Wextra -Werror -pedantic`으로 Phase 3 unit 및 CLI 소스 컴파일
- 합성 SQLite CDB 기반 `PHASE3 UNIT PASS: 41 checks`
- 같은 41 checks를 AddressSanitizer + UndefinedBehaviorSanitizer로 재실행하여 통과
- Phase 2 unit 회귀: `PHASE2 UNIT PASS: 75 checks (Lua calls mocked)`
- 합성 CDB에서 CLI를 동일 입력으로 두 번 실행하여 JSON SHA-256 byte-identical 확인
- `tools/run_phase3_tests.py` Python 문법 검사
- GitHub Actions YAML 파싱 확인

## Actions에서 확인할 항목

작성 환경에는 pinned BabelCDB `cards.cdb` 원본을 별도로 보관하지 않았으므로 실제 Phase 2 고정 DB를 대상으로 하는 Phase 3 통합 검사는 새 Actions에서 확인한다.

성공 기준:

```text
PHASE3 UNIT PASS: 41 checks
PHASE3 SUITE PASS: deterministic candidate pools, explanations, limits, and rejection checks
```

실제 DB 검사는 대표 필수 카드에서 REQUIRED/ENGINE/GENERIC pool, STRONG/MEDIUM 관계, 포함 이유, 상한, 중복 없음, 동일 입력의 byte-identical JSON, 없는 required 카드 거절을 확인한다.
