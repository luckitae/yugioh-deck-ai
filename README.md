# Yu-Gi-Oh! Deck AI

필수 카드를 포함한 Main 40~60장 덱을 만들고, 실제 규칙 엔진에서 플레이하며 승률을 개선하는 프로젝트.

## 현재 제출 범위

**Phase 2 1차 구현: 실제 CDB·Lua·YDK 입력 연결.** Phase 1 합성 카드 테스트는 그대로 보존한다.

이번에 작성한 모듈은 실제 카드 DB 읽기, 카드 정보 콜백, 공통/카드 Lua 로딩, 덱 구조 검증, 단순 실제 효과 통합 검사다. 이것은 강한 플레이 AI나 덱 최적화기의 완성이 아니다.

- 개발/업로드: iPad a-Shell의 `lg2`.
- C++/OCGCore 빌드·실행: GitHub Actions `Build` → `build-core`.
- 고정 데이터: `data/phase2.lock.json`.
- 적용·실행·결과 확인: [docs/PHASE2.md](docs/PHASE2.md).
- 이번 제출의 로컬 검증 범위: [docs/PHASE2_LOCAL_VALIDATION.md](docs/PHASE2_LOCAL_VALIDATION.md).

**주의:** 현재 프로필은 `mr5-no-banlist-smoke-v1`이다. Main/Extra/Side 크기와 DB alias 기준 합산 3장 제한을 검사하지만, 특정 날짜의 OCG/TCG 금제는 적용하지 않는다. 대회 합법성 검사로 사용하지 않는다.

작성 환경에서는 단위 검사와 입력 검증을 수행했다. 실제 원격 데이터와 Lua를 사용하는 통합 검사 결과는 이 커밋의 Actions 실행으로 확인해야 한다. 검사를 작성했다는 사실과 통과했다는 사실을 구분한다.
