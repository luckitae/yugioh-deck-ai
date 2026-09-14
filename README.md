# Yu-Gi-Oh! Deck AI

필수 카드를 포함한 Main 40~60장 덱을 만들고, 실제 규칙 엔진에서 플레이하며 승률을 개선하는 프로젝트.

## 현재 제출 범위

**Phase 3 1차 구현: 실제 카드 데이터에서 설명 가능한 Candidate Pool 생성.** Phase 1·2 회귀 테스트는 그대로 보존한다.

Phase 2의 실제 카드 DB/Lua/YDK 연결 위에 Card Analyzer, Card Graph, Engine/Generic Candidate Pool을 추가한다. 후보마다 포함 이유와 관계를 기록한다. 이것은 아직 강한 플레이 AI나 덱 최적화기의 완성이 아니다.

- 개발/업로드: iPad a-Shell의 `lg2`.
- C++/OCGCore 빌드·실행: GitHub Actions `Build` → `build-core`.
- 고정 데이터: `data/phase2.lock.json`.
- Phase 2 데이터 연결: [docs/PHASE2.md](docs/PHASE2.md).
- Phase 3 적용·분석·검증: [docs/PHASE3.md](docs/PHASE3.md).
- Phase 3 로컬 검증 범위: [docs/PHASE3_LOCAL_VALIDATION.md](docs/PHASE3_LOCAL_VALIDATION.md).
- Phase 2 로컬 검증 범위: [docs/PHASE2_LOCAL_VALIDATION.md](docs/PHASE2_LOCAL_VALIDATION.md).

**주의:** 현재 프로필은 `mr5-no-banlist-smoke-v1`이다. Main/Extra/Side 크기와 DB alias 기준 합산 3장 제한을 검사하지만, 특정 날짜의 OCG/TCG 금제는 적용하지 않는다. 대회 합법성 검사로 사용하지 않는다.

Phase 2 실제 데이터 통합 게이트는 사용자 Actions에서 `PHASE2 SUITE PASS: 39 checks, 8 real-engine duels`로 통과했다. 이번 Phase 3의 실제 고정 DB 후보 분석은 새 커밋의 Actions에서 다시 검증한다.
