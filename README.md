# Yu-Gi-Oh! Deck AI

필수 카드와 최소 채용 매수를 지키는 Main 40~60장 덱을 생성하고, 실제 듀얼 승률로 최적화하는 프로젝트.

## 현재 구현 범위

**Phase 4 1차: Package + 규칙 프로필 + 초기 덱 population 생성.** Phase 1/2/3 회귀 검사는 보존한다.

Phase 2의 실제 DB/Lua/YDK 연결과 Phase 3 후보 분석의 통합 게이트는 사용자 Actions에서 통과했다.
Phase 4는 후보 풀과 명시적 규칙 프로필을 받아 Main 40~60장 전체 범위에서 중복 없는 .ydk 후보를 만든다.
필수 카드/최소 매수, Extra/Side 구분, alias 합산 매수, 프로필별 0/1/2/3장 제한, 패키지 의존성을 검사한다.
**생성된 덱의 승률은 아직 평가하지 않는다.** 기존 smoke 정책으로 효과 카드 덱을 자동 평가하지 않는다.

- 파일 적용/Git: iPad 파일 앱 + a-Shell `lg2`.
- 실제 C++/OCGCore/데이터 통합 검사: GitHub Actions `Build` → `build-core`.
- 고정 데이터: `data/phase2.lock.json` (변경 없음).
- [Phase 4 적용·실행·설계](docs/PHASE4.md)
- [Phase 4 검증 범위](docs/PHASE4_LOCAL_VALIDATION.md)
- [Phase 3 카드 분석](docs/PHASE3.md)
- [Phase 2 데이터 연결](docs/PHASE2.md)

## 합법성/강도에 관한 구분

배포된 Phase 4 기본 프로필은 **`phase4-test-no-banlist-v1` / `test-only`**다.
특정 날짜의 공식 OCG/TCG 금제가 아니다. 날짜별 금제와 지역별 발매 범위의 확정은 남아 있다.
`--rules`는 필수 입력이며, 사용자 지정 JSON 프로필의 금지·제한·준제한 매수는 검사할 수 있다.
프로필 준수와 대회 참가 가능성을 동일시하지 않는다.

패키지는 직접 이름 참조·공유 카드군에 근거한 **탐색용 묶음**이다. 실제로 성립하는 콤보라고 보장하지 않는다.
Phase 3의 기능 점수와 ENGINE/GENERIC 라벨도 휴리스틱이며 강한 덱/진정한 범용성의 증거가 아니다.
다음 작업은 덱·패키지 변이, 후보 품질 개선, 강한 플레이 정책, 실제 듀얼 평가로 연결한다.
