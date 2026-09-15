# Phase 5-A 로컬 검증 범위

## 이 제출본에서 실행한 검사

- `python3 test/phase5_unit.py`
- 결과: `PHASE5-A UNIT PASS: 35 checks (no engine duels)`

검사 범위:

- 저비용 점수 deterministic 계산
- Main 40 vs 60에서 같은 필수 카드 매수의 첫 패 접근성 비교
- 가중치 합/범위 오류 거절
- 6종 mutation 각각 실제 유효 child 생성
- mutation 후 Main 40~60, 필수 카드, Package 유지
- GA 동일 seed 재현성
- generation별 unique population
- elitism에 의한 best prescreen score 비퇴행
- 잘못된 search config 거절

## GitHub Actions에서 추가 확인할 범위

`tools/run_phase5_tests.py`가 Phase 4 실제 고정 DB 산출물을 사용하여 다음을 확인한다.

- 100개 Phase 4 population → 48개 Phase 5-A population
- generation 0 + 4세대
- 동일 입력/seed의 전체 output byte identity
- 다른 seed에서 최종 population 변화
- mutation child 실제 생성
- 모든 최종 YDK를 기존 Phase 4 C++ validator로 교차 검사
- stale Phase 4 provenance/candidate pool 거절
- 잘못된 prescreen 가중치/과도한 population 설정 거절

## 의도적으로 아직 하지 않는 것

- 실제 엔진 듀얼: 0회
- 승률 계산: 없음
- 강한 Our Bot / Opponent Bot: 없음
- Phase 5-A 점수를 승률이라고 해석: 금지
- 공식 특정 날짜 OCG/TCG 금제 인증: 없음

따라서 Actions 성공 문구에도 명시적으로 `0 duels`가 들어간다.
