"""공통 구조/금제 검증. Python 표준 라이브러리만 사용한다.

DB alias 처리와 타입 상수는 고정 OCGCore + Phase 2 deck_loader.cpp 기준이다.
프로필에 기재된 매수 제한 준수와 실제 대회 합법성은 서로 다르다.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

SECTIONS = ("main", "extra", "side")
EXTRA_TYPES = 0x40 | 0x2000 | 0x800000 | 0x4000000
TOKEN = 0x4000


class DeckError(ValueError):
    """잘못된 입력 또는 구조/프로필 제약 위반."""


def integer(value: Any, low: int, high: int, label: str) -> int:
    # bool도 int의 서브클래스이므로 isinstance 대신 정확한 타입을 검사한다.
    if type(value) is not int or not low <= value <= high:
        raise DeckError(f"{label}: expected integer {low}..{high}")
    return value


def card_code(value: Any, label: str = "card code") -> int:
    return integer(value, 1, 0xFFFFFFFF, label)


def keys(obj: Any, allowed: set[str], required: set[str], label: str) -> dict:
    if not isinstance(obj, dict) or not required <= obj.keys() or obj.keys() - allowed:
        raise DeckError(f"{label}: missing/unknown fields")
    return obj


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise DeckError(f"JSON: duplicate key {key}")
        obj[key] = value
    return obj


def read_json(path: Path) -> Any:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise DeckError("JSON input exceeds 32 MiB")
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class Card:
    code: int
    alias: int
    type: int
    scope: int
    name: str

    @property
    def key(self) -> int:
        # Phase 2와 동일한 1단계 DB alias. 카드 텍스트로 이름을 추측하지 않는다.
        return self.alias or self.code

    @property
    def section(self) -> str:
        return "extra" if self.type & EXTRA_TYPES else "main"


class CardCatalog:
    def __init__(self, path: Path):
        if not path.is_file():
            raise DeckError(f"DB missing: {path}")
        self.cards: dict[int, Card] = {}
        # mode=ro: 경로 오타로 빈 DB가 생성되는 것을 방지한다.
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                rows = db.execute("SELECT d.id,d.alias,d.type,d.ot,t.name "
                                  "FROM datas d LEFT JOIN texts t ON d.id=t.id ORDER BY d.id")
                for code, alias, kind, scope, name in rows:
                    code = card_code(code)
                    integer(alias, 0, 0xFFFFFFFF, "DB alias")
                    integer(kind, 0, 0xFFFFFFFF, "DB type")
                    integer(scope, 0, 0xFFFFFFFF, "DB scope")
                    if not isinstance(name, str) or code in self.cards:
                        raise DeckError("DB: missing name or duplicate ID")
                    self.cards[code] = Card(code, alias, kind, scope, name)
        except sqlite3.Error as error:
            raise DeckError(f"DB read/schema error: {error}") from error
        if not self.cards:
            raise DeckError("DB: no cards")

    def __getitem__(self, code: int) -> Card:
        card_code(code)
        try:
            return self.cards[code]
        except KeyError as error:
            raise DeckError(f"unknown card: {code}") from error


class RuleProfile:
    def __init__(self, payload: dict, catalog: CardCatalog):
        fields = {"schema", "id", "kind", "scope_mask", "default_limit", "limits", "source", "note"}
        keys(payload, fields, fields, "rules")
        if type(payload["schema"]) is not int or payload["schema"] != 1:
            raise DeckError("rules: unsupported schema")
        for key in ("id", "source", "note"):
            if not isinstance(payload[key], str) or not payload[key].strip():
                raise DeckError(f"rules: nonempty {key} is required")
        if payload["kind"] not in ("test-only", "custom"):
            raise DeckError("rules kind: test-only or custom; official certification is not supported")
        self.scope = integer(payload["scope_mask"], 1, 3, "scope_mask")
        self.default_limit = integer(payload["default_limit"], 0, 3, "default_limit")
        if not isinstance(payload["limits"], dict):
            raise DeckError("rules: limits must be an object")
        self.group_limits: dict[int, int] = {}
        for text, value in payload["limits"].items():
            if not isinstance(text, str) or not text.isascii() or not text.isdecimal() or str(int(text)) != text:
                raise DeckError("rules: limit keys must be canonical decimal card IDs")
            card = catalog[card_code(int(text))]
            limit = integer(value, 0, 3, "card limit")
            # alias 항목이 중복될 경우 가장 엄격한 제한을 적용한다.
            self.group_limits[card.key] = min(self.group_limits.get(card.key, 3), limit)
        self.payload = payload
        self.catalog = catalog

    def limit(self, code: int) -> int:
        return self.group_limits.get(self.catalog[code].key, self.default_limit)

    def exclusion(self, code: int) -> str | None:
        card = self.catalog[code]
        if not card.scope & self.scope:
            return "outside_profile_scope"
        if card.type & TOKEN or not card.type & 7:
            return "not_a_deck_card"
        if self.limit(code) == 0:
            return "forbidden_by_profile"
        return None

    def check(self, deck: dict[str, list[int]], required: dict[str, dict[int, int]] | None = None,
              complete: bool = True) -> None:
        keys(deck, set(SECTIONS), set(SECTIONS), "deck")
        copies: Counter[int] = Counter()
        for section in SECTIONS:
            items = deck[section]
            if not isinstance(items, list):
                raise DeckError(f"deck {section}: expected list")
            maximum = 60 if section == "main" else 15
            if len(items) > maximum or (complete and section == "main" and len(items) < 40):
                raise DeckError(f"deck {section}: invalid size {len(items)}")
            for code in items:
                card = self.catalog[code]
                reason = self.exclusion(code)
                if reason:
                    raise DeckError(f"{code}: {reason}")
                if section != "side" and card.section != section:
                    raise DeckError(f"{code}: wrong Main/Extra section")
                copies[card.key] += 1
                if copies[card.key] > self.limit(code):
                    raise DeckError(f"copy limit including aliases and Side: {card.key}")
        if required is not None:
            keys(required, {"main", "extra"}, {"main", "extra"}, "required")
            for section, counts in required.items():
                if not isinstance(counts, dict):
                    raise DeckError("required: expected count object")
                actual = Counter(deck[section])
                for code, count in counts.items():
                    card = self.catalog[code]
                    integer(count, 1, 3, "required copies")
                    if card.section != section or actual[code] < count:
                        raise DeckError(f"required {section} missing/wrong section: {code}={count}")


def empty_deck() -> dict[str, list[int]]:
    return {section: [] for section in SECTIONS}


def deck_identity(deck: dict[str, list[int]], catalog: CardCatalog) -> str:
    # alias는 합산 매수 제한용이지 효과 동일성의 증거가 아니다.
    # 항상 같은 이름으로 취급해도 효과가 다른 카드를 중복으로 버리지 않도록 실제 ID를 보존한다.
    normalized = {s: sorted(catalog[code].code for code in deck[s]) for s in SECTIONS}
    return hashlib.sha256(json_text(normalized).encode("utf-8")).hexdigest()


def ydk_text(deck: dict[str, list[int]]) -> str:
    lines = ["#created by yugioh-deck-ai phase4; NOT a win-rate result", "#main"]
    lines += [str(code) for code in sorted(deck["main"])]
    lines += ["#extra"] + [str(code) for code in sorted(deck["extra"])]
    lines += ["!side"] + [str(code) for code in sorted(deck["side"])]
    return "\n".join(lines) + "\n"


def parse_ydk(text: str) -> dict[str, list[int]]:
    deck = empty_deck()
    section = -1
    markers = {"#main": 0, "#extra": 1, "!side": 2}
    for raw in text.lstrip("\ufeff").splitlines():
        if len(raw) > 4096:
            raise DeckError("YDK: line too long")
        line = raw.strip()
        if not line:
            continue
        if line in markers:
            nxt = markers[line]
            if nxt <= section or (section == -1 and nxt != 0):
                raise DeckError("YDK: repeated/out-of-order section")
            section = nxt
            continue
        if line.startswith("#"):
            continue
        if section < 0 or not line.isascii() or not line.isdecimal():
            raise DeckError("YDK: invalid card/section")
        current = deck[SECTIONS[section]]
        current.append(card_code(int(line)))
        if len(current) > (60 if section == 0 else 15):
            raise DeckError("YDK: too many cards")
    if section < 0:
        raise DeckError("YDK: missing #main")
    return deck
