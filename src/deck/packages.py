"""관계 근거가 있는 탐색용 묶음. 실행 가능한 콤보라고 판정하지 않는다."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .rules import DeckError, RuleProfile, card_code, empty_deck, integer, keys


@dataclass(frozen=True)
class Package:
    id: str
    members: tuple[tuple[str, int, int], ...]
    requires: tuple[str, ...]
    evidence: str
    origin: str

    def to_json(self) -> dict:
        return {"id": self.id, "members": [
            {"section": s, "code": code, "count": count} for s, code, count in self.members],
            "requires": list(self.requires), "evidence": self.evidence, "origin": self.origin,
            "combo_verified": False}


def apply_minima(deck: dict[str, list[int]], members: tuple[tuple[str, int, int], ...]) -> dict[str, list[int]]:
    """공유 멤버는 최소 매수의 최댓값으로 합친다. 패키지마다 중복 가산하지 않는다."""
    out = {s: list(items) for s, items in deck.items()}
    for section, code, minimum in members:
        missing = max(0, minimum - out[section].count(code))
        out[section].extend([code] * missing)
    return out


def read_pool(payload: Any, rules: RuleProfile, required: dict[str, dict[int, int]],
              allowed_codes: set[int] | frozenset[int] | None = None) -> tuple[dict[int, dict], list[dict]]:
    if not isinstance(payload, dict) or type(payload.get("schema")) is not int or payload["schema"] != 1:
        raise DeckError("pool: unsupported schema")
    if payload.get("analysis_profile") != "phase3-text-metadata-v1":
        raise DeckError("pool: unsupported analysis profile")
    req = payload.get("required")
    if not isinstance(req, list) or any(type(c) is not int for c in req):
        raise DeckError("pool: invalid required list")
    for code in req:
        rules.catalog[card_code(code)]
    required_codes: set[int] = set()
    for counts in required.values():
        if not isinstance(counts, dict):
            raise DeckError("required: expected count object")
        required_codes.update(counts)
    if len(req) != len(set(req)) or set(req) != required_codes:
        raise DeckError("pool required IDs do not match generator required IDs; regenerate the pool")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 10000:
        raise DeckError("pool: invalid candidate list")
    allowed: dict[int, dict] = {}
    seen: set[int] = set()
    excluded: list[dict] = []
    for row in candidates:
        if not isinstance(row, dict):
            raise DeckError("pool: candidate must be an object")
        code = card_code(row.get("code"))
        rules.catalog[code]
        if code in seen:
            raise DeckError(f"pool: duplicate candidate {code}")
        seen.add(code)
        if row.get("pool") not in ("REQUIRED", "ENGINE", "GENERIC"):
            raise DeckError("pool: invalid pool label")
        if (row["pool"] == "REQUIRED") != (code in req):
            raise DeckError("pool: REQUIRED label does not match required list")
        integer(row.get("score"), 0, 10000000, "candidate score")
        rels = row.get("relations")
        if not isinstance(rels, list) or not rels:
            raise DeckError("pool: missing relation evidence")
        for rel in rels:
            if not isinstance(rel, dict) or rel.get("strength") not in ("STRONG", "MEDIUM", "WEAK"):
                raise DeckError("pool: invalid relation strength")
            ref = integer(rel.get("required_code"), 0, 0xFFFFFFFF, "relation required_code")
            if ref != 0 and ref not in req:
                raise DeckError("pool: relation references a different required card")
            if not isinstance(rel.get("kind"), str) or not isinstance(rel.get("detail"), str):
                raise DeckError("pool: invalid relation text")
        reason = rules.exclusion(code)
        if reason is None and allowed_codes is not None and code not in allowed_codes:
            reason = "experiment_filter"
        if reason:
            if code in req:
                raise DeckError(f"required card excluded: {code} ({reason})")
            excluded.append({"code": code, "reason": reason})
        else:
            allowed[code] = row
    if not set(req) <= allowed.keys():
        raise DeckError("pool: required card absent from candidates")
    return dict(sorted(allowed.items())), sorted(excluded, key=lambda r: r["code"])


def build_packages(candidates: dict[int, dict], rules: RuleProfile, supplied: Any = None,
                   allowed_codes: set[int] | frozenset[int] | None = None) -> dict[str, Package]:
    packages: dict[str, Package] = {}
    if allowed_codes is not None:
        outside = sorted(set(candidates) - set(allowed_codes))
        if outside:
            raise DeckError(f"package candidates outside experiment allowed set: {outside[0]}")
    direct = {"MENTIONS_REQUIRED_NAME", "NAMED_BY_REQUIRED", "SHARED_SETCODE"}
    for code, row in sorted(candidates.items()):
        if row["pool"] != "ENGINE":
            continue
        for rel in row["relations"]:
            anchor = rel["required_code"]
            if rel["kind"] not in direct or anchor not in candidates:
                continue
            if rules.catalog[anchor].key == rules.catalog[code].key:
                continue
            pid = f"auto-{anchor}-{code}"
            members = tuple(sorted(((rules.catalog[anchor].section, anchor, 1),
                                    (rules.catalog[code].section, code, 1))))
            package = Package(pid, members, (), rel["kind"] + ": " + rel["detail"], "phase3-relation")
            try:
                rules.check(apply_minima(empty_deck(), members), complete=False)
            except DeckError:
                continue
            # 같은 카드 쌍은 첫 근거로 고정하고 중복 패키지로 만들지 않는다.
            packages.setdefault(pid, package)
    if supplied is not None:
        keys(supplied, {"schema", "packages"}, {"schema", "packages"}, "packages")
        if type(supplied["schema"]) is not int or supplied["schema"] != 1:
            raise DeckError("packages: unsupported schema")
        items = supplied["packages"]
        if not isinstance(items, list) or len(items) > 1000:
            raise DeckError("packages: expected at most 1000 packages")
        for item in items:
            fields = {"id", "members", "requires", "evidence"}
            keys(item, fields, fields, "package")
            pid = item["id"]
            if (not isinstance(pid, str) or not pid or len(pid) > 120 or
                    pid.startswith("auto-") or pid in packages):
                raise DeckError("package: invalid/reserved/duplicate ID")
            if not isinstance(item["evidence"], str) or not item["evidence"].strip():
                raise DeckError("package: evidence is required")
            reqs = item["requires"]
            if not isinstance(reqs, list) or any(not isinstance(r, str) for r in reqs) or len(reqs) != len(set(reqs)):
                raise DeckError("package: invalid dependencies")
            members = item["members"]
            if not isinstance(members, list) or not 1 <= len(members) <= 70:
                raise DeckError("package: invalid members")
            parsed = []
            seen = set()
            for member in members:
                keys(member, {"section", "code", "count"}, {"section", "code", "count"}, "member")
                section = member["section"]
                code = card_code(member["code"])
                count = integer(member["count"], 1, 3, "package count")
                if section not in ("main", "extra") or code not in candidates or (section, code) in seen:
                    raise DeckError("package: invalid section, duplicate, or card outside eligible pool")
                if allowed_codes is not None and code not in allowed_codes:
                    raise DeckError(f"package: member outside experiment allowed set: {code}")
                seen.add((section, code))
                parsed.append((section, code, count))
            members_tuple = tuple(sorted(parsed))
            rules.check(apply_minima(empty_deck(), members_tuple), complete=False)
            packages[pid] = Package(pid, members_tuple, tuple(sorted(reqs)), item["evidence"], "explicit")
    if len(packages) > 10000:
        raise DeckError("too many packages")
    # 반쯤 적용된 패키지가 남지 않게 모든 의존성을 사용 전 검증한다.
    for pid in packages:
        ordered = package_closure(packages, [pid])
        merged = empty_deck()
        for dependency in ordered:
            merged = apply_minima(merged, packages[dependency].members)
        rules.check(merged, complete=False)
    return dict(sorted(packages.items()))


def package_closure(packages: dict[str, Package], requested: list[str]) -> list[str]:
    # 재귀 대신 명시적 DFS 스택: 긴 입력도 RecursionError로 끝나지 않는다.
    status: dict[str, int] = {}
    out: list[str] = []
    for root in sorted(set(requested)):
        stack = [(root, False)]
        while stack:
            pid, exit_node = stack.pop()
            if pid not in packages:
                raise DeckError(f"unknown package dependency: {pid}")
            if exit_node:
                status[pid] = 2
                out.append(pid)
                continue
            if status.get(pid) == 2:
                continue
            if status.get(pid) == 1:
                raise DeckError(f"package dependency cycle: {pid}")
            status[pid] = 1
            stack.append((pid, True))
            for dep in reversed(packages[pid].requires):
                stack.append((dep, False))
    return out


def check_packages(deck: dict[str, list[int]], packages: dict[str, Package], selected: list[str],
                   allowed_codes: set[int] | frozenset[int] | None = None) -> None:
    if set(package_closure(packages, selected)) != set(selected):
        raise DeckError("selected package is missing a dependency")
    for pid in selected:
        for section, code, count in packages[pid].members:
            if allowed_codes is not None and code not in allowed_codes:
                raise DeckError(f"selected package contains card outside experiment allowed set: {pid}, {code}")
            if Counter(deck[section])[code] < count:
                raise DeckError(f"broken package member: {pid}, {code}")
