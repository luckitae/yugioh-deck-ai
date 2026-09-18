# Yu-Gi-Oh! Deck AI

필수 카드와 최소 채용 매수를 지키는 Main 40~60장 덱을 생성하고, 실제 OCGCore 듀얼 승률로 최적화하는 프로젝트.

## 현재 구현 범위

**Phase 5-C: 실제 OCGCore 반복 듀얼 승률을 GA Fitness에 연결.** Phase 1~5-B 회귀 검사를 보존한다.

- Phase 2: 고정 실제 Card DB/Lua/YDK 연결
- Phase 3: Required Card → 설명 가능한 Engine/Generic candidate pool
- Phase 4: 40~60장 제약 보존 초기 population 생성
- Phase 5-A: 제약 보존 GA + 저비용 prescreen
- Phase 5-B: 실제 OCGCore Duel Runner + deterministic legal-response baseline Bot
- Phase 5-C: opponent split + candidate × opponent × seed × 선/후공 반복 평가 + 실제 승률 Fitness

Phase 5-C의 `score_ppm`은 schedule이 전부 완료된 경우 **실제 `win_rate_ppm`과 동일**하다. timeout, unsupported selection, protocol/resource/engine 오류가 하나라도 있으면 해당 평가를 승률로 발표하지 않고 `score_ppm=-1`로 실격한다.

상대 Pool은 `training`, `validation`, `final` split을 분리한다. 전체/상대별/선공/후공 승률과 개별 result/trace/log를 모두 남긴다.

`first-legal-v1`은 여전히 **강한 플레이 AI가 아니다.** Phase 5-C Actions 통합 시험의 상대도 경쟁 덱이라고 주장하지 않는 `test-only` 일반 몬스터 fixture다. 따라서 이 단계의 숫자는 실제 엔진 승률이지만 최종 메타 성능 수치가 아니다.

- 파일 적용/Git: iPad 파일 앱 + a-Shell `lg2`
- 실제 C++/OCGCore/데이터 통합 검사: GitHub Actions `Build` → `build-core`
- 고정 데이터: `data/phase2.lock.json`
- [Phase 5 설계/현재 범위](docs/PHASE5.md)
- [Phase 5 로컬 검증 범위](docs/PHASE5_LOCAL_VALIDATION.md)
- [Phase 4 설계](docs/PHASE4.md)
- [Phase 3 카드 분석](docs/PHASE3.md)
- [Phase 2 데이터 연결](docs/PHASE2.md)

## 다음 우선순위

Phase 5-C 실제 데이터 게이트가 통과하면 현실적인 pinned opponent Pool과 더 강한 state-aware 플레이 정책을 도입한다. 그 뒤 seed/상대 수와 GA 예산을 늘리고, Phase 6에서 듀얼 trace로 필수 카드 사용률·반복 전개·승리 패턴·선공/후공 플레이법을 추출한다.

Phase 4부터 사용하는 기본 rules profile은 특정 날짜 공식 OCG/TCG 금제 인증이 아니다. 공식 환경 고정은 별도 작업으로 남아 있다.
