#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import random
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from deck.packages import Package, check_packages
from deck.rules import DeckError, SECTIONS, deck_identity
from search.fitness import LowCostWeights, PPM, low_cost_evaluate, required_access_ppm
from search.ga import OPERATIONS, SearchConfig, mutate_once, run_search

checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    if not condition:
        raise AssertionError(message)
    checks += 1


@dataclass(frozen=True)
class FakeCard:
    code: int
    section: str = "main"
    key: int = 0

    def __post_init__(self):
        if self.key == 0:
            object.__setattr__(self, "key", self.code)


class FakeCatalog:
    def __init__(self):
        self.cards = {code: FakeCard(code) for code in range(1, 31)}
        self.cards.update({100 + code: FakeCard(100 + code, "extra") for code in range(1, 8)})

    def __getitem__(self, code: int) -> FakeCard:
        if code not in self.cards:
            raise DeckError(f"unknown card: {code}")
        return self.cards[code]


class FakeRules:
    def __init__(self):
        self.catalog = FakeCatalog()

    def limit(self, code: int) -> int:
        return 3

    def check(self, deck, required=None, complete=True):
        if set(deck) != set(SECTIONS):
            raise DeckError("sections")
        if len(deck["main"]) > 60 or (complete and len(deck["main"]) < 40):
            raise DeckError("main size")
        if len(deck["extra"]) > 15 or len(deck["side"]) > 15:
            raise DeckError("other size")
        used = Counter()
        for section in SECTIONS:
            for code in deck[section]:
                card = self.catalog[code]
                if section != "side" and card.section != section:
                    raise DeckError("section")
                used[card.key] += 1
                if used[card.key] > 3:
                    raise DeckError("copies")
        if required:
            for section in ("main", "extra"):
                actual = Counter(deck[section])
                for code, count in required[section].items():
                    if actual[code] < count:
                        raise DeckError("required")


def make_fixture():
    rules = FakeRules()
    candidates = {}
    for code in range(1, 31):
        candidates[code] = {"code": code, "pool": "REQUIRED" if code == 1 else ("ENGINE" if code % 2 == 0 else "GENERIC"),
                            "score": 1000 - code * 10}
    for code in range(101, 108):
        candidates[code] = {"code": code, "pool": "ENGINE", "score": 600}
    required = {"main": {1: 2}, "extra": {}}
    packages = {
        "pA": Package("pA", (("main", 2, 2), ("main", 4, 1)), (), "test", "unit"),
        "pB": Package("pB", (("main", 6, 2),), ("pA",), "test", "unit"),
    }
    base = [1, 1]
    for code in range(2, 16):
        base.extend([code, code, code])
    base = base[:44]
    # ensure required count remains 2 and pA is complete
    while base.count(2) < 2:
        base.append(2)
    while base.count(4) < 1:
        base.append(4)
    deck = {"main": sorted(base), "extra": [], "side": [], "selected_packages": ["pA"]}
    rules.check({s: deck[s] for s in SECTIONS}, required)
    check_packages({s: deck[s] for s in SECTIONS}, packages, deck["selected_packages"])
    return rules, candidates, required, packages, deck


def main() -> int:
    rules, candidates, required, packages, deck = make_fixture()
    weights = LowCostWeights(700, 300)
    weights.validate(); check(True, "weights")
    try:
        LowCostWeights(700, 301).validate()
        check(False, "invalid weights accepted")
    except ValueError:
        check(True, "invalid weight rejected")

    deck40 = {"main": [1, 1] + list(range(2, 15)) * 3, "extra": [], "side": []}
    deck40["main"] = deck40["main"][:40]
    # maintain two required copies after slicing
    deck60 = {"main": deck40["main"] + [20, 20, 21, 21, 22, 22, 23, 23, 24, 24, 25, 25, 26, 26, 27, 27, 28, 28, 29, 29],
              "extra": [], "side": []}
    a40 = required_access_ppm(deck40, required)
    a60 = required_access_ppm(deck60, required)
    check(0 < a60 < a40 < PPM, "required access must reward smaller Main with same copies")
    check(low_cost_evaluate(deck, candidates, required, weights)["score_ppm"] > 0, "low cost score positive")
    check(low_cost_evaluate(deck, candidates, required, weights) == low_cost_evaluate(deck, candidates, required, weights), "deterministic score")

    # 모든 mutation 연산이 유효한 child를 만들 수 있는 fixture를 각각 찾는다.
    op_success = {}
    for operation in OPERATIONS:
        parent = dict(deck)
        if operation == "package_remove":
            parent = {**deck, "selected_packages": ["pA"]}
        if operation == "package_add":
            parent = {**deck, "selected_packages": []}
        child = None
        for seed in range(200):
            child = mutate_once(parent, operation, candidates, packages, rules, required, random.Random(seed))
            if child is not None:
                break
        check(child is not None, f"{operation} should produce at least one valid child")
        rules.check({s: child[s] for s in SECTIONS}, required)
        check_packages({s: child[s] for s in SECTIONS}, packages, child["selected_packages"])
        check(40 <= len(child["main"]) <= 60, f"{operation} main bounds")
        check(child["main"].count(1) >= 2, f"{operation} preserves required")
        op_success[operation] = child
    check(set(op_success) == set(OPERATIONS), "all operations exercised")

    # 12개 고유 seed population을 만든다.
    initial = []
    for index in range(12):
        candidate = {"main": list(deck["main"]), "extra": [], "side": [], "selected_packages": ["pA"]}
        # removable slot 하나를 서로 다른 코드로 치환해 identity를 분리한다.
        old = next(code for code in candidate["main"] if code not in (1, 2, 4) and candidate["main"].count(code) > 1)
        candidate["main"].remove(old)
        new = 16 + index
        candidate["main"].append(new)
        candidate["main"].sort()
        rules.check({s: candidate[s] for s in SECTIONS}, required)
        initial.append(candidate)
    check(len({deck_identity(row, rules.catalog) for row in initial}) == 12, "unique initial")

    evaluator = lambda row: low_cost_evaluate(row, candidates, required, weights)
    config = SearchConfig(population_size=8, generations=3, elite_count=2, tournament_size=3,
                          mutation_attempts=120, seed=77)
    first = run_search(initial, candidates, packages, rules, required, evaluator, config)
    second = run_search(initial, candidates, packages, rules, required, evaluator, config)
    serial1 = [(x["deck_id"], x["metrics"]) for x in first["population"]]
    serial2 = [(x["deck_id"], x["metrics"]) for x in second["population"]]
    check(serial1 == serial2 and first["history"] == second["history"], "search deterministic")
    check(len(first["population"]) == 8, "search population size")
    check(all(h["unique"] == 8 for h in first["history"]), "unique every generation")
    check(all(first["history"][i + 1]["best_score_ppm"] >= first["history"][i]["best_score_ppm"]
              for i in range(len(first["history"]) - 1)), "elitism prevents best regression")
    check(sum(first["operation_counts"].values()) > 0, "mutation children accepted")
    for row in first["population"]:
        rules.check({s: row[s] for s in SECTIONS}, required)
        check_packages({s: row[s] for s in SECTIONS}, packages, row["selected_packages"])
    check(True, "final population validates")

    for bad in (
        SearchConfig(1, 1, 1, 2, 10, 1),
        SearchConfig(8, 0, 2, 3, 10, 1),
        SearchConfig(8, 2, 8, 3, 10, 1),
        SearchConfig(8, 2, 2, 1, 10, 1),
    ):
        try:
            bad.validate(); check(False, "bad config accepted")
        except DeckError:
            check(True, "bad config rejected")

    print(f"PHASE5-A UNIT PASS: {checks} checks (no engine duels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
