#!/usr/bin/env python3
"""고정 실 DB: 카드 분석 -> Package -> .ydk population -> 기존 C++ 로더 교차 검증.

이 suite는 효과 카드가 있는 덱을 듀얼시키지 않는다. 테스트 정책을 승률 평가로 오용하지 않는다.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from deck.packages import build_packages, check_packages, read_pool
from deck.rules import CardCatalog, RuleProfile, deck_identity, json_text, parse_ydk, read_json, sha256

ART = ROOT / "artifacts/phase4"
DB = ROOT / "data/vendor/BabelCDB/cards.cdb"
RULES = ROOT / "data/rules/phase4-test-no-banlist.json"
ANALYZER = ROOT / "phase3_analyze"
VALIDATOR = ROOT / "phase4_validate"
REQUIRED = {"main": {89631139: 2}, "extra": {}}


def run(name: str, command: list[str], expect_ok: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=180)
    (ART / f"{name}.log").write_text(result.stdout, encoding="utf-8")
    if (result.returncode == 0) != expect_ok:
        raise RuntimeError(f"{name}: unexpected exit={result.returncode}\n{result.stdout}")
    return result


def analyze(name: str, required: dict) -> Path:
    output = ART / f"{name}_pool.json"
    command = [str(ANALYZER), "--db", str(DB), "--engine-limit", "160", "--generic-limit", "100",
               "--total-limit", "280", "--output", str(output)]
    for code in sorted(set(required["main"]) | set(required["extra"])):
        command += ["--required", str(code)]
    run(name + "_analyze", command)
    return output


def generate(name: str, pool: Path, required: dict, count: int = 21, seed: int = 1,
             rules_path: Path = RULES, extra: list[str] | None = None, expect_ok: bool = True) -> Path:
    output = ART / name
    command = [sys.executable, str(ROOT / "tools/phase4_generate.py"), "--db", str(DB),
               "--pool", str(pool), "--rules", str(rules_path), "--output", str(output),
               "--count", str(count), "--seed", str(seed)]
    for section, counts in required.items():
        for code, minimum in sorted(counts.items()):
            command += [f"--required-{section}", f"{code}={minimum}"]
    command += extra or []
    run(name, command, expect_ok)
    if not expect_ok and output.exists():
        raise RuntimeError("failed generation exposed an output population")
    return output


def validate_population(directory: Path, pool: Path, required: dict, catalog: CardCatalog,
                        rules_path: Path = RULES, expected_count: int = 21) -> dict:
    payload = read_json(directory / "population.json")
    rules = RuleProfile(read_json(rules_path), catalog)
    candidates, excluded = read_pool(read_json(pool), rules, required)
    packages = build_packages(candidates, rules)
    decks = payload["decks"]
    if len(decks) != expected_count or len({d["deck_id"] for d in decks}) != expected_count:
        raise RuntimeError("population count/uniqueness failed")
    if {len(d["main"]) for d in decks} != set(range(40, 61)):
        raise RuntimeError("Main 40..60 coverage failed")
    if any(payload[k] is not False for k in ("tournament_legality_verified", "win_rate_evaluated", "package_combo_verified")):
        raise RuntimeError("unverified results presented as verified")
    if payload["input_sha256"]["database"] != sha256(DB) or payload["input_sha256"]["rules"] != sha256(rules_path):
        raise RuntimeError("provenance hash mismatch")
    if payload["excluded_candidates"] != excluded:
        raise RuntimeError("candidate exclusion report mismatch")
    command = [str(VALIDATOR), "--db", str(DB)]
    for code, minimum in required["main"].items():
        command += ["--required-main", f"{code}={minimum}"]
    for deck in decks:
        relative = Path(deck["file"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("unsafe output path")
        path = directory / relative
        parsed = parse_ydk(path.read_text(encoding="utf-8"))
        if any(parsed[section] != deck[section] for section in ("main", "extra", "side")):
            raise RuntimeError("YDK/manifest mismatch")
        rules.check(parsed, required)
        check_packages(parsed, packages, deck["selected_packages"])
        if deck["deck_id"] != deck_identity(parsed, catalog):
            raise RuntimeError("deck ID mismatch")
        if any(code not in candidates for section in parsed.values() for code in section):
            raise RuntimeError("generator added a card outside eligible pool")
        command += ["--deck", str(path)]
    run(directory.name + "_cpp_validation", command)
    print(f"PASS {directory.name}: {expected_count} unique decks, Main 40..60, Python + C++ validation")
    return payload


def tree_hashes(directory: Path) -> dict[str, str]:
    return {str(p.relative_to(directory)): sha256(p) for p in sorted(directory.rglob("*")) if p.is_file()}


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    try:
        if not all(path.is_file() for path in (DB, RULES, ANALYZER, VALIDATOR)):
            raise RuntimeError("required Phase 2 DB / Phase 3 analyzer / Phase 4 validator missing")
        catalog = CardCatalog(DB)
        rules = RuleProfile(read_json(RULES), catalog)
        pool = analyze("single", REQUIRED)
        first = generate("population_a", pool, REQUIRED, count=100)
        a = validate_population(first, pool, REQUIRED, catalog, expected_count=100)
        second = generate("population_b", pool, REQUIRED, count=100)
        if tree_hashes(first) != tree_hashes(second):
            raise RuntimeError("same inputs did not yield byte-identical complete artifacts")
        print("PASS repeat: byte-identical YDK + population.json + packages.json")

        multi_req = {"main": {89631139: 2, 46986414: 1}, "extra": {}}
        multi_pool = analyze("multi", multi_req)
        multi = generate("multiple_required", multi_pool, multi_req, seed=42)
        validate_population(multi, multi_pool, multi_req, catalog)

        candidates, _ = read_pool(read_json(pool), rules, REQUIRED)
        extras = sorted(code for code in candidates if catalog[code].section == "extra")
        if not extras:
            raise RuntimeError("fixture has no eligible Extra candidate")
        extra_req = {"main": {89631139: 2}, "extra": {extras[0]: 1}}
        extra_pool = analyze("extra", extra_req)
        extra_out = generate("required_extra", extra_pool, extra_req)
        validate_population(extra_out, extra_pool, extra_req, catalog)

        # 제한 처리는 임의 fixture로 검증한다. 공식 금제라고 주장하지 않는다.
        optional = []
        seen = {catalog[code].key for code in REQUIRED["main"]}
        for code in sorted(candidates):
            card = catalog[code]
            if card.section == "main" and card.key not in seen:
                seen.add(card.key)
                optional.append(code)
            if len(optional) == 3:
                break
        if len(optional) < 3:
            raise RuntimeError("not enough independent fixture cards for 0/1/2 limits")
        restricted = copy.deepcopy(rules.payload)
        restricted.update(id="phase4-test-limits-0-1-2-v1", limits={str(code): i for i, code in enumerate(optional)})
        restricted_path = ART / "test-limits.json"
        restricted_path.write_text(json_text(restricted), encoding="utf-8")
        limited_out = generate("limited_profile", pool, REQUIRED, rules_path=restricted_path, extra=["--side-size", "15"])
        validate_population(limited_out, pool, REQUIRED, catalog, restricted_path)

        packages = build_packages(candidates, rules)
        if not packages:
            raise RuntimeError("fixture has no relation packages")
        forced_id = next((pid for pid, p in packages.items() if any(s == "extra" for s, _, _ in p.members)), next(iter(packages)))
        forced_out = generate("forced_package", pool, REQUIRED, extra=["--force-package", forced_id])
        forced_payload = validate_population(forced_out, pool, REQUIRED, catalog)
        if not all(forced_id in d["selected_packages"] for d in forced_payload["decks"]):
            raise RuntimeError("forced package was silently dropped")

        banned = copy.deepcopy(rules.payload)
        banned["limits"] = {"89631139": 0}
        banned_path = ART / "test-banned-required.json"
        banned_path.write_text(json_text(banned), encoding="utf-8")
        generate("reject_banned_required", pool, REQUIRED, rules_path=banned_path, expect_ok=False)
        generate("reject_four_required", pool, {"main": {89631139: 4}, "extra": {}}, expect_ok=False)
        generate("reject_stale_pool", pool, multi_req, expect_ok=False)
        generate("reject_size39", pool, REQUIRED, extra=["--sizes", "39"], expect_ok=False)
        generate("reject_size61", pool, REQUIRED, extra=["--sizes", "61"], expect_ok=False)
        generate("reject_extra16", pool, REQUIRED, extra=["--extra-size", "16"], expect_ok=False)
        generate("reject_missing_package", pool, REQUIRED, extra=["--force-package", "missing"], expect_ok=False)
        # 작은 Phase 3 풀은 용량 부족을 제약 완화 대신 명시적으로 거절해야 한다.
        tiny = read_json(pool)
        tiny["candidates"] = [r for r in tiny["candidates"] if r["pool"] == "REQUIRED"]
        tiny_path = ART / "tiny_pool.json"
        tiny_path.write_text(json_text(tiny), encoding="utf-8")
        generate("reject_insufficient_pool", tiny_path, REQUIRED, expect_ok=False)
        print("PASS rejection checks: invalid sizes/counts, forbidden required, stale pool, missing package, insufficient pool")
        summary = {"schema": 1, "status": "pass", "main_population": len(a["decks"]),
                   "cpp_validated_decks": 184, "byte_identical_repeat": True,
                   "main_sizes": list(range(40, 61)), "real_engine_duels_in_phase4": 0,
                   "db_sha256": sha256(DB), "lock_sha256": sha256(ROOT / "data/phase2.lock.json"),
                   "rule_profile": rules.payload["id"], "tournament_legality_verified": False}
        (ART / "suite.json").write_text(json_text(summary), encoding="utf-8")
        print("PHASE4 SUITE PASS: 100 unique decks, 40..60 coverage, deterministic output, rules, packages, C++ validation")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        (ART / "suite_error.txt").write_text(str(error) + "\n", encoding="utf-8")
        print(f"PHASE4 SUITE FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
