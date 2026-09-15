"""시도 횟수를 제한한 초기 population 생성기. 승률 추정/최적화/플레이 정책이 아니다."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import random

from .packages import Package, apply_minima, check_packages, package_closure
from .rules import DeckError, RuleProfile, SECTIONS, deck_identity, empty_deck, integer

VERSION = "phase4-package-population-v1"


@dataclass(frozen=True)
class GenerationConfig:
    count: int = 100
    sizes: tuple[int, ...] = tuple(range(40, 61))
    seed: int = 1
    extra_size: int | None = None
    side_size: int = 0
    max_packages: int = 3
    attempts_per_deck: int = 100

    def validate(self) -> None:
        integer(self.count, 1, 10000, "count")
        integer(self.seed, 0, (1 << 64) - 1, "seed")
        integer(self.side_size, 0, 15, "side_size")
        integer(self.max_packages, 0, 20, "max_packages")
        integer(self.attempts_per_deck, 1, 1000, "attempts_per_deck")
        if self.extra_size is not None:
            integer(self.extra_size, 0, 15, "extra_size")
        if not self.sizes or len(self.sizes) > 21:
            raise DeckError("sizes: specify 1..21 Main sizes")
        for size in self.sizes:
            integer(size, 40, 60, "Main size")
        if tuple(sorted(set(self.sizes))) != self.sizes:
            raise DeckError("sizes must be unique and increasing")
        if self.count < len(self.sizes):
            raise DeckError("count must cover every requested Main size at least once")


def _copies(deck: dict[str, list[int]], rules: RuleProfile) -> Counter[int]:
    return Counter(rules.catalog[code].key for section in SECTIONS for code in deck[section])


def remaining_capacity(deck: dict[str, list[int]], codes: list[int], rules: RuleProfile) -> int:
    used = _copies(deck, rules)
    groups = {rules.catalog[code].key: rules.limit(code) for code in codes}
    return sum(max(0, limit - used[key]) for key, limit in groups.items())


def _fits(deck: dict[str, list[int]], target: dict[str, int], rules: RuleProfile) -> bool:
    if any(len(deck[s]) > target[s] for s in SECTIONS):
        return False
    try:
        rules.check(deck, complete=False)
        return True
    except DeckError:
        return False


def _available(deck: dict[str, list[int]], targets: dict[str, int],
               by_section: dict[str, list[int]], rules: RuleProfile) -> bool:
    if not _fits(deck, targets, rules):
        return False
    for section in SECTIONS:
        if remaining_capacity(deck, by_section[section], rules) < targets[section] - len(deck[section]):
            return False
    # Main/Extra/Side가 같은 alias 잔여 매수를 이중으로 예약하지 않도록 전체도 검사한다.
    all_codes = sorted(set(by_section["main"] + by_section["extra"]))
    return remaining_capacity(deck, all_codes, rules) >= sum(targets[s] - len(deck[s]) for s in SECTIONS)


def generate_population(candidates: dict[int, dict], packages: dict[str, Package], rules: RuleProfile,
                        required: dict[str, dict[int, int]], config: GenerationConfig,
                        forced: list[str] | None = None) -> dict:
    config.validate()
    base = empty_deck()
    for section, counts in required.items():
        if section not in ("main", "extra") or not isinstance(counts, dict):
            raise DeckError("invalid required section/counts")
        for code, count in counts.items():
            integer(count, 1, 3, "required copies")
            if code not in candidates:
                raise DeckError(f"required outside eligible pool: {code}")
            base[section].extend([code] * count)
    if not any(required.values()):
        raise DeckError("at least one required card must be specified")
    rules.check(base, required, complete=False)
    closure = package_closure(packages, forced or [])
    for pid in closure:
        base = apply_minima(base, packages[pid].members)
    rules.check(base, required, complete=False)

    by_section = {s: sorted(code for code in candidates if rules.catalog[code].section == s)
                  for s in ("main", "extra")}
    by_section["side"] = sorted(candidates)
    extra_target = config.extra_size
    if extra_target is None:
        extra_target = min(15, len(base["extra"]) + remaining_capacity(base, by_section["extra"], rules))
    targets = {"main": min(config.sizes), "extra": extra_target, "side": config.side_size}
    if not _fits(base, targets, rules):
        raise DeckError("required/forced packages exceed a requested section size")
    for size in config.sizes:
        targets["main"] = size
        if not _available(base, targets, by_section, rules):
            raise DeckError(f"eligible pool has insufficient capacity for Main={size}, Extra={extra_target}, Side={config.side_size}")

    rng = random.Random(config.seed)
    seen: set[str] = set()
    output: list[dict] = []
    total_attempts = duplicate_attempts = failed_attempts = 0
    optional = sorted(set(packages) - set(closure))
    # 순서를 항상 40..60 순환으로 고정해 작은 덱만 채워지는 편향을 방지한다.
    for index in range(config.count):
        targets["main"] = config.sizes[index % len(config.sizes)]
        accepted = False
        for _ in range(config.attempts_per_deck):
            total_attempts += 1
            deck = {s: list(base[s]) for s in SECTIONS}
            selected = set(closure)
            options = list(optional)
            rng.shuffle(options)
            limit = rng.randrange(config.max_packages + 1)
            chosen_roots = 0
            for pid in options:
                if chosen_roots >= limit:
                    break
                proposal = {s: list(deck[s]) for s in SECTIONS}
                pending = package_closure(packages, [pid])
                for dependency in pending:
                    proposal = apply_minima(proposal, packages[dependency].members)
                if _available(proposal, targets, by_section, rules):
                    deck = proposal
                    selected.update(pending)
                    chosen_roots += 1
            # 이는 soft sampling 비중이다. 실제 카드 비율/승률을 보장하는 제약이 아니다.
            generic_percent = (10, 25, 40)[index % 3]
            failed = False
            used = _copies(deck, rules)
            for section in SECTIONS:
                while len(deck[section]) < targets[section]:
                    available = [code for code in by_section[section]
                                 if used[rules.catalog[code].key] < rules.limit(code)]
                    if not available:
                        failed = True
                        break
                    generic = [code for code in available if candidates[code]["pool"] == "GENERIC"]
                    engine = [code for code in available if candidates[code]["pool"] != "GENERIC"]
                    preferred = generic if rng.randrange(100) < generic_percent else engine
                    choices = preferred or available
                    weights = [2 if candidates[code]["pool"] == "REQUIRED" else
                               1 + min(200, candidates[code]["score"]) // 20 for code in choices]
                    draw = rng.randrange(sum(weights))
                    selected_code = choices[-1]
                    for code, weight in zip(choices, weights):
                        if draw < weight:
                            selected_code = code
                            break
                        draw -= weight
                    deck[section].append(selected_code)
                    used[rules.catalog[selected_code].key] += 1
                if failed:
                    break
            if failed:
                failed_attempts += 1
                continue
            for section in SECTIONS:
                deck[section].sort()
            # 후조건은 별도 판정기를 통해 매 후보마다 다시 검사한다.
            rules.check(deck, required)
            selected_ids = sorted(selected)
            check_packages(deck, packages, selected_ids)
            fingerprint = deck_identity(deck, rules.catalog)
            if fingerprint in seen:
                duplicate_attempts += 1
                continue
            seen.add(fingerprint)
            counts = Counter(candidates[code]["pool"] for code in deck["main"])
            output.append({"deck_id": fingerprint, "main": deck["main"], "extra": deck["extra"],
                           "side": deck["side"], "selected_packages": selected_ids,
                           "main_pool_counts": {key: counts[key] for key in ("REQUIRED", "ENGINE", "GENERIC")},
                           "generic_sampling_percent": generic_percent})
            accepted = True
            break
        if not accepted:
            raise DeckError(f"sampling budget exhausted: generated {len(output)}/{config.count} unique decks; "
                            "not a proof that the requested population is impossible")
    return {"decks": output, "attempts": total_attempts, "duplicate_attempts": duplicate_attempts,
            "failed_attempts": failed_attempts, "effective_extra_size": extra_target}
