# Yu-Gi-Oh! Deck AI

필수 카드와 최소 채용 매수를 지키는 Main 40~60장 덱을 생성하고, 실제 OCGCore 듀얼 승률로 최적화하는 프로젝트.

## 현재 구현 범위

**Phase 5-B: 실제 OCGCore Duel Runner + deterministic legal-response baseline Bot.** Phase 1~5-A 회귀 검사를 보존한다.

- Phase 2: 고정 실제 Card DB/Lua/YDK 연결
- Phase 3: Required Card → 설명 가능한 Engine/Generic candidate pool
- Phase 4: 40~60장 제약 보존 초기 population 생성
- Phase 5-A: 제약 보존 GA + 저비용 prescreen
- Phase 5-B: 실제 OCGCore에서 덱 두 개를 끝까지 플레이하고 승패/턴/선택/행동 trace 기록

Phase 5-B의 `first-legal-v1`은 **강한 플레이 AI가 아니다.** 엔진이 제시한 합법 선택 중 deterministic한 첫 행동을 고르는 baseline이다. `IDLE/BATTLE/CHAIN/CARD/PLACE/POSITION/TRIBUTE/COUNTER/SUM` 등 주요 선택을 파싱하며, 지원하지 못한 선택은 임의 응답하지 않고 `unsupported_selection`으로 실패한다.

Actions 통합 시험은 Phase 5-A 상위 2개 덱을 고정 DB의 40장 일반 몬스터 fixture와 실제 OCGCore에서 양쪽 좌석·2개 seed로 총 8판 실행한다. 이 결과는 **실제 엔진 듀얼**이지만, 상대가 메타 덱 Pool이 아니므로 최종 Fitness 승률로 사용하지 않는다.

- 파일 적용/Git: iPad 파일 앱 + a-Shell `lg2`
- 실제 C++/OCGCore/데이터 통합 검사: GitHub Actions `Build` → `build-core`
- 고정 데이터: `data/phase2.lock.json`
- [Phase 5 설계/현재 범위](docs/PHASE5.md)
- [Phase 5 로컬 검증 범위](docs/PHASE5_LOCAL_VALIDATION.md)
- [Phase 4 설계](docs/PHASE4.md)
- [Phase 3 카드 분석](docs/PHASE3.md)
- [Phase 2 데이터 연결](docs/PHASE2.md)

## 아직 최종 결과가 아닌 이유

Phase 4 기본 룰 프로필은 특정 날짜 공식 OCG/TCG 금제가 아닌 test-only 프로필이다. 날짜별 금제·발매 범위 확정은 별도 작업이다.

Phase 3 관계 점수, Package, Phase 5-A prescreen은 모두 탐색 휴리스틱이다. Phase 5-B baseline Bot도 강한 플레이 정책이 아니다. 다음 단계는 Phase 5-B Duel Runner를 **반복 대전 evaluator**로 묶고, 일반적인 상대 덱 Pool·선공/후공 반복 seed를 도입해 실제 승률을 GA Fitness의 최우선 지표로 연결하는 것이다.
