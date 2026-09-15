"""Phase 5-A의 저비용 선별 지표.

이 모듈은 듀얼 승률을 추정하지 않는다. 필수 카드 접근성과 Phase 3 관계 점수만으로
비싼 실제 듀얼 전에 후보를 줄이는 deterministic prescreen 전용이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import comb
from typing import Any

PPM = 1_000_000


@dataclass(frozen=True)
class LowCostWeights:
    required_access: int = 700
    relation_quality: int = 300

    def validate(self) -> None:
        if type(self.required_access) is not int or type(self.relation_quality) is not int:
            raise ValueError("low-cost weights must be integers")
        if self.required_access < 0 or self.relation_quality < 0:
            raise ValueError("low-cost weights must be nonnegative")
        if self.required_access + self.relation_quality != 1000:
            raise ValueError("low-cost weights must sum to 1000")


def _access_ppm(deck_size: int, copies: int, opening_hand: int = 5) -> int:
    if type(deck_size) is not int or type(copies) is not int:
        raise ValueError("deck_size/copies must be integers")
    if deck_size < opening_hand or not 0 <= copies <= deck_size:
        raise ValueError("invalid deck_size/copies")
    if copies == 0:
        return 0
    miss_pool = deck_size - copies
    miss = 0 if miss_pool < opening_hand else comb(miss_pool, opening_hand)
    total = comb(deck_size, opening_hand)
    return ((total - miss) * PPM + total // 2) // total


def required_access_ppm(deck: dict[str, list[int]], required: dict[str, dict[int, int]]) -> int:
    """Main 필수 카드 각각을 첫 5장에서 볼 확률의 산술 평균.

    사용자가 요구한 최소 매수가 아니라 실제 덱의 해당 카드 매수를 사용한다. Extra 필수 카드는
    opening hand 접근성 개념이 없으므로 이 값에는 넣지 않는다.
    """
    main = deck["main"]
    if not required.get("main"):
        return PPM
    values = [_access_ppm(len(main), main.count(code)) for code in sorted(required["main"])]
    return sum(values) // len(values)


def relation_quality_ppm(deck: dict[str, list[int]], candidates: dict[int, dict[str, Any]]) -> int:
    """Main의 Phase 3 score를 현재 후보 pool의 최대 score로 정규화한 평균.

    이 값은 카드 강도나 실제 콤보 성공률이 아니다.
    """
    if not deck["main"]:
        return 0
    maximum = max((int(row["score"]) for row in candidates.values()), default=0)
    if maximum <= 0:
        return 0
    total = 0
    for code in deck["main"]:
        if code not in candidates:
            raise ValueError(f"card outside candidate pool: {code}")
        score = int(candidates[code]["score"])
        if score < 0:
            raise ValueError("negative candidate score")
        total += min(PPM, (score * PPM + maximum // 2) // maximum)
    return total // len(deck["main"])


def low_cost_evaluate(deck: dict[str, list[int]], candidates: dict[int, dict[str, Any]],
                      required: dict[str, dict[int, int]], weights: LowCostWeights) -> dict[str, int]:
    weights.validate()
    access = required_access_ppm(deck, required)
    relation = relation_quality_ppm(deck, candidates)
    # 정수만 사용하여 플랫폼별 float 차이를 없앤다. 결과 범위는 0..1,000,000.
    score = (access * weights.required_access + relation * weights.relation_quality + 500) // 1000
    return {
        "score_ppm": score,
        "required_opening_access_ppm": access,
        "relation_quality_ppm": relation,
    }
