"""제약을 보존하는 Phase 5-A 유전 탐색 코어.

실제 듀얼 evaluator와 독립된 search kernel이다. 현재 기본 evaluator는 fitness.py의
low-cost prescreen이며 결과를 승률로 표시하지 않는다.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import random
from typing import Any, Callable

from deck.experiment import ExperimentSpec, check_allowed_deck
from deck.packages import Package, apply_minima, check_packages, package_closure
from deck.rules import DeckError, RuleProfile, SECTIONS, deck_identity

Evaluator = Callable[[dict[str, list[int]]], dict[str, int]]


@dataclass(frozen=True)
class SearchConfig:
    population_size: int = 48
    generations: int = 4
    elite_count: int = 8
    tournament_size: int = 4
    mutation_attempts: int = 80
    seed: int = 1

    def validate(self) -> None:
        values = (self.population_size, self.generations, self.elite_count,
                  self.tournament_size, self.mutation_attempts, self.seed)
        if any(type(value) is not int for value in values):
            raise DeckError("search config values must be integers")
        if not 2 <= self.population_size <= 10000:
            raise DeckError("population_size must be 2..10000")
        if not 1 <= self.generations <= 10000:
            raise DeckError("generations must be 1..10000")
        if not 1 <= self.elite_count < self.population_size:
            raise DeckError("elite_count must be 1..population_size-1")
        if not 2 <= self.tournament_size <= self.population_size:
            raise DeckError("tournament_size must be 2..population_size")
        if not 1 <= self.mutation_attempts <= 10000:
            raise DeckError("mutation_attempts must be 1..10000")
        if not 0 <= self.seed <= (1 << 64) - 1:
            raise DeckError("seed must be uint64")


def _copy(deck: dict[str, list[int]]) -> dict[str, list[int]]:
    return {section: list(deck[section]) for section in SECTIONS}


def _selected_roots(packages: dict[str, Package], selected: list[str]) -> list[str]:
    selected_set = set(selected)
    depended = {dep for pid in selected for dep in packages[pid].requires if dep in selected_set}
    return sorted(selected_set - depended)


def _protected_minima(required: dict[str, dict[int, int]], packages: dict[str, Package],
                      selected: list[str]) -> dict[str, Counter[int]]:
    protected = {section: Counter() for section in SECTIONS}
    for section, counts in required.items():
        if section not in protected:
            raise DeckError(f"invalid required section: {section}")
        for code, count in counts.items():
            protected[section][code] = max(protected[section][code], count)
    for pid in selected:
        for section, code, count in packages[pid].members:
            protected[section][code] = max(protected[section][code], count)
    return protected


def _used_aliases(deck: dict[str, list[int]], rules: RuleProfile) -> Counter[int]:
    return Counter(rules.catalog[code].key for section in SECTIONS for code in deck[section])


def _available(candidates: dict[int, dict[str, Any]], deck: dict[str, list[int]],
               rules: RuleProfile, section: str, pool: str | None = None,
               allowed_codes: set[int] | frozenset[int] | None = None) -> list[int]:
    used = _used_aliases(deck, rules)
    result = []
    for code, row in candidates.items():
        if allowed_codes is not None and code not in allowed_codes:
            continue
        card = rules.catalog[code]
        if card.section != section or (pool is not None and row["pool"] != pool):
            continue
        if used[card.key] < rules.limit(code):
            result.append(code)
    return sorted(result)


def _normalise(deck: dict[str, list[int]]) -> None:
    for section in SECTIONS:
        deck[section].sort()


def _valid(deck: dict[str, list[int]], selected: list[str], packages: dict[str, Package],
           rules: RuleProfile, required: dict[str, dict[int, int]],
           allowed_codes: set[int] | frozenset[int] | None = None,
           experiment: ExperimentSpec | None = None) -> bool:
    try:
        rules.check(deck, required)
        check_allowed_deck(deck, allowed_codes, "GA deck")
        if experiment is not None:
            experiment.check_deck(deck, rules.catalog, rules)
        check_packages(deck, packages, selected, allowed_codes)
        return True
    except DeckError:
        return False


def _remove_one(deck: dict[str, list[int]], section: str, code: int) -> None:
    deck[section].remove(code)


def mutate_once(parent: dict[str, Any], operation: str, candidates: dict[int, dict[str, Any]],
                packages: dict[str, Package], rules: RuleProfile,
                required: dict[str, dict[int, int]], rng: random.Random,
                allowed_codes: set[int] | frozenset[int] | None = None,
                experiment: ExperimentSpec | None = None) -> dict[str, Any] | None:
    deck = _copy(parent)
    if allowed_codes is not None:
        try:
            check_allowed_deck(deck, allowed_codes, "mutation parent")
        except DeckError:
            return None
    selected = sorted(set(parent.get("selected_packages", [])))
    protected = _protected_minima(required, packages, selected)

    if operation == "replace_card":
        removable = [code for code in deck["main"] if deck["main"].count(code) > protected["main"][code]]
        if not removable:
            return None
        old = rng.choice(sorted(set(removable)))
        proposal = _copy(deck)
        _remove_one(proposal, "main", old)
        choices = [code for code in _available(candidates, proposal, rules, "main", allowed_codes=allowed_codes) if code != old]
        if not choices:
            return None
        proposal["main"].append(rng.choice(choices))
        deck = proposal

    elif operation == "copy_up":
        if len(deck["main"]) >= 60:
            return None
        used = _used_aliases(deck, rules)
        choices = sorted(set(code for code in deck["main"]
                             if used[rules.catalog[code].key] < rules.limit(code)))
        if not choices:
            return None
        deck["main"].append(rng.choice(choices))

    elif operation == "copy_down":
        if len(deck["main"]) <= 40:
            return None
        choices = sorted(set(code for code in deck["main"]
                             if deck["main"].count(code) > protected["main"][code]))
        if not choices:
            return None
        _remove_one(deck, "main", rng.choice(choices))

    elif operation == "pool_rebalance":
        # ENGINE <-> GENERIC 교체. REQUIRED는 절대 제거하지 않는다.
        pairs: list[tuple[int, str]] = []
        for code in sorted(set(deck["main"])):
            if deck["main"].count(code) <= protected["main"][code]:
                continue
            label = candidates[code]["pool"]
            if label == "ENGINE":
                pairs.append((code, "GENERIC"))
            elif label == "GENERIC":
                pairs.append((code, "ENGINE"))
        if not pairs:
            return None
        old, wanted = rng.choice(pairs)
        proposal = _copy(deck)
        _remove_one(proposal, "main", old)
        choices = _available(candidates, proposal, rules, "main", wanted, allowed_codes)
        if not choices:
            return None
        proposal["main"].append(rng.choice(choices))
        deck = proposal

    elif operation == "package_add":
        choices = sorted(set(packages) - set(selected))
        if not choices:
            return None
        pid = rng.choice(choices)
        add = package_closure(packages, [pid])
        proposal = _copy(deck)
        for dependency in add:
            proposal = apply_minima(proposal, packages[dependency].members)
        if len(proposal["main"]) > 60 or len(proposal["extra"]) > 15:
            return None
        selected = sorted(set(selected) | set(add))
        deck = proposal

    elif operation == "package_remove":
        roots = _selected_roots(packages, selected)
        if not roots:
            return None
        removed = rng.choice(roots)
        keep_roots = [pid for pid in roots if pid != removed]
        keep = package_closure(packages, keep_roots) if keep_roots else []
        old_selected = set(selected)
        selected = sorted(set(keep))
        new_protected = _protected_minima(required, packages, selected)
        proposal = _copy(deck)
        affected: list[tuple[str, int]] = []
        for pid in sorted(old_selected - set(selected)):
            affected.extend((section, code) for section, code, _ in packages[pid].members)
        changed = False
        for section, code in sorted(set(affected)):
            minimum = new_protected[section][code]
            floor = 40 if section == "main" else 0
            while proposal[section].count(code) > minimum and len(proposal[section]) > floor:
                _remove_one(proposal, section, code)
                changed = True
        if not changed:
            return None
        deck = proposal

    else:
        raise DeckError(f"unknown mutation operation: {operation}")

    _normalise(deck)
    if not _valid(deck, selected, packages, rules, required, allowed_codes, experiment):
        return None
    return {**deck, "selected_packages": selected, "mutation": operation}


OPERATIONS = ("replace_card", "copy_up", "copy_down", "pool_rebalance", "package_add", "package_remove")


def _rank(individuals: list[dict[str, Any]], evaluator: Evaluator,
          rules: RuleProfile) -> list[dict[str, Any]]:
    ranked = []
    for item in individuals:
        metrics = evaluator(item)
        ranked.append({**item, "metrics": metrics, "deck_id": deck_identity(item, rules.catalog)})
    return sorted(ranked, key=lambda row: (-row["metrics"]["score_ppm"], row["deck_id"]))


def run_search(initial: list[dict[str, Any]], candidates: dict[int, dict[str, Any]],
               packages: dict[str, Package], rules: RuleProfile,
               required: dict[str, dict[int, int]], evaluator: Evaluator,
               config: SearchConfig, operations: tuple[str, ...] = OPERATIONS,
               allowed_codes: set[int] | frozenset[int] | None = None,
               experiment: ExperimentSpec | None = None) -> dict[str, Any]:
    config.validate()
    if not operations or len(set(operations)) != len(operations) or any(op not in OPERATIONS for op in operations):
        raise DeckError("operations must be a unique nonempty subset of OPERATIONS")
    if len(initial) < config.population_size:
        raise DeckError("initial population smaller than search population_size")
    if allowed_codes is not None:
        outside = sorted(set(candidates) - set(allowed_codes))
        if outside:
            raise DeckError(f"GA candidates outside experiment allowed set: {outside[0]}")
        for pid, package in packages.items():
            for _, code, _ in package.members:
                if code not in allowed_codes:
                    raise DeckError(f"GA package outside experiment allowed set: {pid}, {code}")
    clean: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in initial:
        deck = {section: list(source[section]) for section in SECTIONS}
        selected = sorted(set(source.get("selected_packages", [])))
        _normalise(deck)
        if not _valid(deck, selected, packages, rules, required, allowed_codes, experiment):
            raise DeckError("invalid initial individual")
        identity = deck_identity(deck, rules.catalog)
        if identity in seen:
            continue
        seen.add(identity)
        clean.append({**deck, "selected_packages": selected, "origin": "phase4"})
    if len(clean) < config.population_size:
        raise DeckError("not enough unique valid initial individuals")

    rng = random.Random(config.seed)
    ranked = _rank(clean, evaluator, rules)[:config.population_size]
    history: list[dict[str, Any]] = []
    operation_counts = Counter()
    mutation_failures = 0

    for generation in range(config.generations + 1):
        scores = [row["metrics"]["score_ppm"] for row in ranked]
        history.append({"generation": generation, "best_score_ppm": max(scores),
                        "mean_score_ppm": sum(scores) // len(scores), "worst_score_ppm": min(scores),
                        "unique": len(ranked)})
        if generation == config.generations:
            break
        next_population = [{k: v for k, v in row.items() if k not in ("metrics", "deck_id")}
                           for row in ranked[:config.elite_count]]
        next_ids = {deck_identity(row, rules.catalog) for row in next_population}
        attempts = 0
        limit = config.population_size * config.mutation_attempts
        while len(next_population) < config.population_size and attempts < limit:
            attempts += 1
            tournament = rng.sample(ranked, config.tournament_size)
            parent = min(tournament, key=lambda row: (-row["metrics"]["score_ppm"], row["deck_id"]))
            operation = rng.choice(operations)
            child = mutate_once(parent, operation, candidates, packages, rules, required, rng,
                                allowed_codes, experiment)
            if child is None:
                mutation_failures += 1
                continue
            identity = deck_identity(child, rules.catalog)
            if identity in next_ids:
                mutation_failures += 1
                continue
            child["origin"] = "mutation"
            child["parent_deck_id"] = parent["deck_id"]
            next_population.append(child)
            next_ids.add(identity)
            operation_counts[operation] += 1
        if len(next_population) < config.population_size:
            raise DeckError(f"mutation budget exhausted at generation {generation + 1}: "
                            f"{len(next_population)}/{config.population_size}")
        ranked = _rank(next_population, evaluator, rules)

    return {"population": ranked, "history": history,
            "operation_counts": {key: operation_counts[key] for key in OPERATIONS},
            "mutation_failures": mutation_failures}
