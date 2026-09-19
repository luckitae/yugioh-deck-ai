"""R1 ExperimentSpec: strict normalization plus one shared candidate-allowance contract."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Iterable

from .rules import (
    CardCatalog,
    DeckError,
    RuleProfile,
    SECTIONS,
    card_code,
    integer,
    json_text,
    keys,
    read_json,
    sha256,
)

TYPE_MONSTER = 0x1
TYPE_NORMAL = 0x10
TYPE_PENDULUM = 0x1000000


@dataclass(frozen=True)
class RequiredCard:
    code: int
    section: str
    minimum: int
    maximum: int


@dataclass(frozen=True)
class CandidateFilter:
    exclude_normal_monsters: bool
    exclude_pendulum: bool
    exceptions: frozenset[int]


@dataclass(frozen=True)
class ExperimentSpec:
    required: tuple[RequiredCard, ...]
    main_min: int
    main_max: int
    extra_min: int
    extra_max: int
    side_min: int
    side_max: int
    candidate_filter: CandidateFilter
    normalized: dict[str, Any]
    experiment_id: str

    def allows(self, code: int, catalog: CardCatalog) -> bool:
        card = catalog[code]
        if code in self.candidate_filter.exceptions:
            return True
        if (self.candidate_filter.exclude_normal_monsters and
                card.type & TYPE_MONSTER and card.type & TYPE_NORMAL):
            return False
        if self.candidate_filter.exclude_pendulum and card.type & TYPE_PENDULUM:
            return False
        return True

    def required_minima(self) -> dict[str, dict[int, int]]:
        out = {section: {} for section in SECTIONS}
        for row in self.required:
            if row.minimum > 0:
                out[row.section][row.code] = row.minimum
        return out

    def check_deck(self, deck: dict[str, list[int]], catalog: CardCatalog,
                   rules: RuleProfile, complete: bool = True) -> None:
        """Validate the user's own deck against the normalized experiment.

        The candidate filter applies only here/to our search candidates.  It does not
        remove cards from the execution DB and is never applied to opponent decks.
        """
        required = self.required_minima()
        rules.check(deck, required, complete=False)
        for section in SECTIONS:
            for code in deck[section]:
                if not self.allows(code, catalog):
                    raise DeckError(f"experiment deck: card outside experiment allowed set: {code}")
        bounds = {
            "main": (self.main_min, self.main_max),
            "extra": (self.extra_min, self.extra_max),
            "side": (self.side_min, self.side_max),
        }
        for section in SECTIONS:
            size = len(deck[section])
            low, high = bounds[section]
            if size > high or (complete and size < low):
                raise DeckError(f"experiment deck {section}: size {size} outside {low}..{high}")
        counts = {section: Counter(deck[section]) for section in SECTIONS}
        for row in self.required:
            actual = counts[row.section][row.code]
            if actual > row.maximum or (complete and actual < row.minimum):
                raise DeckError(
                    f"required {row.section} count outside {row.minimum}..{row.maximum}: "
                    f"{row.code}={actual}"
                )


@dataclass(frozen=True)
class PreparedExperiment:
    spec: ExperimentSpec
    allowed_codes: frozenset[int]
    allowed_sha256: str
    directory: Path


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise DeckError(f"{label}: expected boolean")
    return value


def _range(obj: Any, label: str, low: int, high: int) -> tuple[int, int]:
    keys(obj, {"min", "max"}, {"min", "max"}, label)
    minimum = integer(obj["min"], low, high, f"{label}.min")
    maximum = integer(obj["max"], low, high, f"{label}.max")
    if minimum > maximum:
        raise DeckError(f"{label}: min exceeds max")
    return minimum, maximum


def parse_experiment(payload: Any, catalog: CardCatalog, rules: RuleProfile) -> ExperimentSpec:
    p = keys(payload, {"schema", "deck", "candidate_filter"},
             {"schema", "deck", "candidate_filter"}, "experiment")
    if p["schema"] != 1:
        raise DeckError("experiment: unsupported schema")
    deck = keys(p["deck"], {"required", "main", "extra", "side"},
                {"required", "main", "extra", "side"}, "experiment.deck")
    main_min, main_max = _range(deck["main"], "deck.main", 40, 60)
    extra_min, extra_max = _range(deck["extra"], "deck.extra", 0, 15)
    side_min, side_max = _range(deck["side"], "deck.side", 0, 15)
    if not isinstance(deck["required"], list) or not deck["required"]:
        raise DeckError("deck.required: expected nonempty list")

    required: list[RequiredCard] = []
    seen: set[tuple[str, int]] = set()
    for raw in deck["required"]:
        row = keys(raw, {"code", "section", "min", "max"},
                   {"code", "section", "min", "max"}, "required card")
        code = card_code(row["code"], "required code")
        card = catalog[code]
        section = row["section"]
        if section not in SECTIONS:
            raise DeckError("required card: section must be main/extra/side")
        minimum = integer(row["min"], 0, 3, "required min")
        maximum = integer(row["max"], 0, 3, "required max")
        if minimum > maximum or maximum == 0:
            raise DeckError("required card: invalid min/max")
        if section != "side" and card.section != section:
            raise DeckError(f"required card wrong section: {code}")
        reason = rules.exclusion(code)
        if reason:
            raise DeckError(f"required card excluded by rules: {code} ({reason})")
        if maximum > rules.limit(code):
            raise DeckError(f"required max exceeds rule copy limit: {code}")
        identity = (section, code)
        if identity in seen:
            raise DeckError(f"duplicate required card: {section}:{code}")
        seen.add(identity)
        required.append(RequiredCard(code, section, minimum, maximum))

    raw_filter = keys(
        p["candidate_filter"],
        {"exclude_normal_monsters", "exclude_pendulum", "exceptions"},
        {"exclude_normal_monsters", "exclude_pendulum", "exceptions"},
        "candidate_filter",
    )
    normal = _boolean(raw_filter["exclude_normal_monsters"],
                      "candidate_filter.exclude_normal_monsters")
    pendulum = _boolean(raw_filter["exclude_pendulum"],
                        "candidate_filter.exclude_pendulum")
    if not isinstance(raw_filter["exceptions"], list):
        raise DeckError("candidate_filter.exceptions: expected list")
    exceptions: set[int] = set()
    for raw in raw_filter["exceptions"]:
        code = card_code(raw, "filter exception")
        catalog[code]
        if code in exceptions:
            raise DeckError(f"duplicate filter exception: {code}")
        exceptions.add(code)

    policy = CandidateFilter(normal, pendulum, frozenset(exceptions))
    required.sort(key=lambda item: (item.section, item.code))
    normalized: dict[str, Any] = {
        "schema": 1,
        "deck": {
            "required": [
                {"code": row.code, "section": row.section,
                 "min": row.minimum, "max": row.maximum}
                for row in required
            ],
            "main": {"min": main_min, "max": main_max},
            "extra": {"min": extra_min, "max": extra_max},
            "side": {"min": side_min, "max": side_max},
        },
        "candidate_filter": {
            "exclude_normal_monsters": normal,
            "exclude_pendulum": pendulum,
            "exceptions": sorted(exceptions),
        },
    }
    draft = ExperimentSpec(
        tuple(required), main_min, main_max, extra_min, extra_max, side_min, side_max,
        policy, normalized, "",
    )
    for row in required:
        if row.minimum > 0 and not draft.allows(row.code, catalog):
            raise DeckError(
                f"required card conflicts with candidate filter: {row.code}; "
                "add explicit exception to allow it"
            )
    experiment_id = hashlib.sha256(json_text(normalized).encode("utf-8")).hexdigest()
    return ExperimentSpec(
        tuple(required), main_min, main_max, extra_min, extra_max, side_min, side_max,
        policy, normalized, experiment_id,
    )


def load_experiment(path: Path, catalog: CardCatalog, rules: RuleProfile) -> ExperimentSpec:
    return parse_experiment(read_json(path), catalog, rules)


def build_allowed_set(spec: ExperimentSpec, catalog: CardCatalog,
                      rules: RuleProfile) -> list[int]:
    allowed = [
        code for code in sorted(catalog.cards)
        if rules.exclusion(code) is None and spec.allows(code, catalog)
    ]
    if not {row.code for row in spec.required if row.minimum > 0} <= set(allowed):
        raise DeckError("required cards are not contained in allowed candidate set")
    return allowed


def allowed_set_text(codes: Iterable[int]) -> str:
    normalized = sorted(set(codes))
    if not normalized:
        raise DeckError("allowed set is empty")
    return "".join(f"{card_code(code, 'allowed code')}\n" for code in normalized)


def allowed_set_sha256(codes: Iterable[int]) -> str:
    return hashlib.sha256(allowed_set_text(codes).encode("ascii")).hexdigest()


def check_allowed_deck(deck: dict[str, list[int]], allowed_codes: Iterable[int] | None,
                       label: str = "deck") -> None:
    if allowed_codes is None:
        return
    allowed = set(allowed_codes)
    if not allowed:
        raise DeckError("allowed set is empty")
    for section in SECTIONS:
        items = deck.get(section)
        if not isinstance(items, list):
            raise DeckError(f"{label} {section}: expected list")
        forbidden: set[int] = set()
        for raw_code in items:
            code = card_code(raw_code, f"{label} {section} card")
            if code not in allowed:
                forbidden.add(code)
        if forbidden:
            raise DeckError(f"{label}: card outside experiment allowed set: {min(forbidden)}")


def load_prepared_experiment(directory: Path, catalog: CardCatalog, rules: RuleProfile,
                             db_path: Path | None = None,
                             rules_path: Path | None = None) -> PreparedExperiment:
    directory = directory.resolve()
    manifest_path = directory / "experiment.normalized.json"
    manifest = read_json(manifest_path)
    keys(manifest,
         {"schema", "experiment_id", "normalized_spec", "allowed_set", "input_sha256"},
         {"schema", "experiment_id", "normalized_spec", "allowed_set", "input_sha256"},
         "prepared experiment")
    if manifest["schema"] != 1:
        raise DeckError("prepared experiment: unsupported schema")
    if not isinstance(manifest["experiment_id"], str) or len(manifest["experiment_id"]) != 64:
        raise DeckError("prepared experiment: invalid experiment_id")
    spec = parse_experiment(manifest["normalized_spec"], catalog, rules)
    if spec.experiment_id != manifest["experiment_id"]:
        raise DeckError("prepared experiment: normalized spec ID mismatch")

    block = keys(manifest["allowed_set"], {"count", "sha256", "file"},
                 {"count", "sha256", "file"}, "prepared allowed_set")
    if type(block["count"]) is not int or block["count"] <= 0:
        raise DeckError("prepared allowed_set: invalid count")
    if not isinstance(block["sha256"], str) or len(block["sha256"]) != 64:
        raise DeckError("prepared allowed_set: invalid sha256")
    if block["file"] != "allowed_ids.txt":
        raise DeckError("prepared allowed_set: unsupported file")
    allowed_path = directory / "allowed_ids.txt"
    raw = allowed_path.read_text(encoding="ascii")
    if sha256(allowed_path) != block["sha256"]:
        raise DeckError("prepared allowed_set: file hash mismatch")
    codes: list[int] = []
    for line in raw.splitlines():
        if not line or not line.isascii() or not line.isdecimal() or str(int(line)) != line:
            raise DeckError("prepared allowed_set: non-canonical card ID")
        code = card_code(int(line), "prepared allowed code")
        catalog[code]
        codes.append(code)
    if codes != sorted(set(codes)) or len(codes) != block["count"]:
        raise DeckError("prepared allowed_set: duplicate/order/count mismatch")
    expected = build_allowed_set(spec, catalog, rules)
    if codes != expected or allowed_set_sha256(codes) != block["sha256"]:
        raise DeckError("prepared allowed_set: does not match normalized experiment")

    inputs = keys(manifest["input_sha256"], {"spec", "database", "rules"},
                  {"spec", "database", "rules"}, "prepared input_sha256")
    if db_path is not None and inputs["database"] != sha256(db_path):
        raise DeckError("prepared experiment: database hash mismatch")
    if rules_path is not None and inputs["rules"] != sha256(rules_path):
        raise DeckError("prepared experiment: rules hash mismatch")
    for key in ("spec", "database", "rules"):
        if not isinstance(inputs[key], str) or len(inputs[key]) != 64:
            raise DeckError(f"prepared experiment: invalid {key} hash")

    return PreparedExperiment(spec, frozenset(codes), block["sha256"], directory)
