#!/usr/bin/env python3
"""합성 카드 DB로 Phase 4 불변조건을 검사한다. 실제 카드 효과 검증은 아니다."""
from __future__ import annotations

from dataclasses import replace
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from deck.generator import GenerationConfig, generate_population
from deck.packages import apply_minima, build_packages, check_packages, read_pool
from deck.rules import (CardCatalog, DeckError, RuleProfile, deck_identity, empty_deck,
                        json_text, parse_ydk, read_json, ydk_text)
from phase4_generate import main as cli_main, parse_required, parse_sizes, write_population


def create_fixture(directory: Path) -> tuple[Path, dict, dict]:
    db_path = directory / "fixture.cdb"
    with sqlite3.connect(db_path) as db:
        db.executescript("CREATE TABLE datas(id INTEGER PRIMARY KEY, ot INTEGER, alias INTEGER, "
                         "setcode INTEGER, type INTEGER, atk INTEGER, def INTEGER, level INTEGER, "
                         "race INTEGER, attribute INTEGER, category INTEGER);"
                         "CREATE TABLE texts(id INTEGER PRIMARY KEY,name TEXT,desc TEXT);")
        rows = [(code, 3, 0, 4660 if code < 140 else 0, 33 if code < 140 else 2,
                 1500, 1000, 4, 1, 16, 0) for code in range(100, 180)]
        rows += [(code, 3, 0, 4660, 0x41, 2500, 2000, 8, 1, 16, 0) for code in range(200, 208)]
        rows += [(300, 3, 100, 0, 33, 1500, 1000, 4, 1, 16, 0),
                 (301, 3, 0, 0, 0x4001, 0, 0, 1, 1, 1, 0),
                 (302, 4, 0, 0, 33, 0, 0, 1, 1, 1, 0),
                 (303, 2, 0, 0, 33, 0, 0, 1, 1, 1, 0)]
        db.executemany("INSERT INTO datas VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        for row in rows:
            code = row[0]
            name = "Alpha Dragon" if code == 100 else f"Card {code}"
            text = ('If this card is Normal Summoned: add 1 "Alpha Dragon" from your Deck to your hand.'
                    if 100 < code < 140 or 200 <= code < 208 else
                    "Draw 2 cards, then destroy 1 card." if 140 <= code < 180 else "A normal monster.")
            db.execute("INSERT INTO texts VALUES(?,?,?)", (code, name, text))
    profile = json.loads((ROOT / "data/rules/phase4-test-no-banlist.json").read_text())
    candidates = []
    for row in rows:
        code = row[0]
        pool = "REQUIRED" if code == 100 else "GENERIC" if 140 <= code < 180 else "ENGINE"
        relation = {"required_code": 0 if pool == "GENERIC" else 100,
                    "strength": "WEAK" if pool == "GENERIC" else "STRONG",
                    "kind": "GENERIC_UTILITY" if pool == "GENERIC" else
                            "REQUIRED_SELF" if code == 100 else "MENTIONS_REQUIRED_NAME",
                    "detail": "synthetic fixture", "score": 100}
        candidates.append({"code": code, "name": f"Card {code}", "pool": pool,
                           "score": 1000000 if code == 100 else 100,
                           "features": [], "relations": [relation]})
    payload = {"schema": 1, "analysis_profile": "phase3-text-metadata-v1",
               "required": [100], "config": {}, "candidates": candidates}
    return db_path, profile, payload


class Phase4Tests(unittest.TestCase):
    generated_decks = 0

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="phase4-unit-")
        self.directory = Path(self.temp.name)
        self.db_path, self.profile, self.payload = create_fixture(self.directory)
        self.catalog = CardCatalog(self.db_path)
        self.rules = RuleProfile(self.profile, self.catalog)
        self.required = {"main": {100: 2}, "extra": {}}
        self.candidates, self.excluded = read_pool(self.payload, self.rules, self.required)
        self.packages = build_packages(self.candidates, self.rules)
        self.config = GenerationConfig(count=21)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def generate(self, config=None, rules=None, packages=None, forced=None) -> dict:
        result = generate_population(self.candidates, packages if packages is not None else self.packages,
                                     rules or self.rules, self.required, config or self.config, forced)
        type(self).generated_decks += len(result["decks"])
        return result

    def legal(self) -> dict:
        return {"main": [100, 100] + list(range(101, 139)), "extra": [200], "side": []}

    def package_payload(self, requires=None) -> dict:
        return {"schema": 1, "packages": [{"id": "bundle", "evidence": "test only",
                "requires": requires or [], "members": [
                    {"section": "main", "code": 101, "count": 2},
                    {"section": "extra", "code": 200, "count": 1}]}]}

    def test_all_21_sizes_required_and_uniqueness(self):
        result = self.generate()
        self.assertEqual({len(d["main"]) for d in result["decks"]}, set(range(40, 61)))
        self.assertEqual(len({d["deck_id"] for d in result["decks"]}), 21)
        for d in result["decks"]:
            deck = {s: d[s] for s in ("main", "extra", "side")}
            self.rules.check(deck, self.required)
            check_packages(deck, self.packages, d["selected_packages"])
            self.assertGreaterEqual(deck["main"].count(100), 2)
            self.assertEqual(len(deck["extra"]), 15)
            self.assertEqual(deck["side"], [])

    def test_100_deck_population_and_seed_repeat(self):
        config = replace(self.config, count=100)
        a, b = self.generate(config), self.generate(config)
        self.assertEqual(json_text(a), json_text(b))
        self.assertEqual(len(a["decks"]), 100)
        c = self.generate(replace(config, seed=42))
        self.assertNotEqual(a["decks"][0]["deck_id"], c["decks"][0]["deck_id"])

    def test_multi_seed_property_invariants(self):
        for seed in range(10):
            config = replace(self.config, seed=seed, side_size=15)
            for d in self.generate(config)["decks"]:
                self.rules.check({s: d[s] for s in ("main", "extra", "side")}, self.required)
                check_packages({s: d[s] for s in ("main", "extra", "side")}, self.packages, d["selected_packages"])
                self.assertEqual(len(d["side"]), 15)

    def test_filter_tokens_and_scope(self):
        self.assertNotIn(301, self.candidates)
        self.assertNotIn(302, self.candidates)
        self.assertEqual({r["code"] for r in self.excluded}, {301, 302})
        self.profile["scope_mask"] = 1
        rules = RuleProfile(self.profile, self.catalog)
        cand, _ = read_pool(self.payload, rules, self.required)
        self.assertNotIn(303, cand)

    def test_structure_rejects_39_61(self):
        for size in (39, 61):
            deck = self.legal()
            deck["main"] = list(range(100, 100 + size))
            with self.assertRaises(DeckError):
                self.rules.check(deck)

    def test_extra_side_16(self):
        for section in ("extra", "side"):
            deck = self.legal()
            deck[section] = [200] * 16
            with self.assertRaises(DeckError):
                self.rules.check(deck)

    def test_wrong_sections(self):
        for section, code in (("main", 200), ("extra", 100)):
            deck = self.legal()
            deck[section].append(code)
            with self.assertRaises(DeckError):
                self.rules.check(deck)

    def test_missing_required_not_satisfied_by_side(self):
        deck = self.legal()
        deck["main"][0] = 140
        deck["side"] = [100]
        with self.assertRaises(DeckError):
            self.rules.check(deck, self.required)

    def test_alias_total_across_side(self):
        deck = self.legal()
        deck["side"] = [300, 300]
        with self.assertRaises(DeckError):
            self.rules.check(deck)
        deck["side"] = [300]
        self.rules.check(deck)

    def test_banned_limited_semilimited(self):
        for code, limit in ((101, 0), (101, 1), (101, 2)):
            self.profile["limits"] = {str(code): limit}
            rules = RuleProfile(self.profile, self.catalog)
            deck = self.legal()
            deck["side"] = [code] * limit
            with self.assertRaises(DeckError):
                rules.check(deck)
        self.profile["limits"] = {"100": 1}
        with self.assertRaises(DeckError):
            self.generate(rules=RuleProfile(self.profile, self.catalog))

    def test_alias_limits_strictest(self):
        self.profile["limits"] = {"100": 2, "300": 1}
        rules = RuleProfile(self.profile, self.catalog)
        self.assertEqual(rules.limit(100), 1)
        self.assertEqual(rules.limit(300), 1)

    def test_whitelist_default_zero(self):
        self.profile["default_limit"] = 0
        self.profile["limits"] = {str(code): 3 for code in range(100, 125)}
        rules = RuleProfile(self.profile, self.catalog)
        candidates, _ = read_pool(self.payload, rules, self.required)
        result = generate_population(candidates, {}, rules, self.required, replace(self.config, extra_size=0))
        self.assertTrue(all(set(d["main"]) <= set(range(100, 125)) | {300} for d in result["decks"]))

    def test_forbidden_required_rejected(self):
        self.profile["limits"] = {"100": 0}
        with self.assertRaises(DeckError):
            read_pool(self.payload, RuleProfile(self.profile, self.catalog), self.required)

    def test_bad_profile_fields(self):
        for key, value in (("scope_mask", 4), ("scope_mask", True), ("default_limit", 4),
                           ("default_limit", -1), ("kind", "official"), ("schema", True),
                           ("source", ""), ("limits", []), ("limits", {"100": True}),
                           ("limits", {"0100": 0}), ("limits", {"99999": 0})):
            profile = copy.deepcopy(self.profile)
            profile[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(DeckError):
                RuleProfile(profile, self.catalog)
        self.profile["limitz"] = {}
        with self.assertRaises(DeckError):
            RuleProfile(self.profile, self.catalog)

    def test_empty_missing_bad_db(self):
        missing = self.directory / "missing.cdb"
        with self.assertRaises(DeckError):
            CardCatalog(missing)
        self.assertFalse(missing.exists())
        bad = self.directory / "bad.cdb"
        bad.write_text("not sqlite")
        with self.assertRaises(DeckError):
            CardCatalog(bad)

    def test_duplicate_json_keys(self):
        path = self.directory / "bad.json"
        path.write_text('{"schema":1,"limits":{"100":0,"100":3}}')
        with self.assertRaises(DeckError):
            read_json(path)

    def test_pool_missing_mismatched_duplicate(self):
        variants = []
        p = copy.deepcopy(self.payload); p["required"] = [101]; variants.append(p)
        p = copy.deepcopy(self.payload); p["candidates"] = p["candidates"][1:]; variants.append(p)
        p = copy.deepcopy(self.payload); p["candidates"].append(p["candidates"][0]); variants.append(p)
        p = copy.deepcopy(self.payload); p["candidates"][1]["code"] = 999999; variants.append(p)
        p = copy.deepcopy(self.payload); p["schema"] = True; variants.append(p)
        p = copy.deepcopy(self.payload); p["candidates"][1]["score"] = True; variants.append(p)
        p = copy.deepcopy(self.payload); p["candidates"][1]["relations"] = []; variants.append(p)
        for p in variants:
            with self.assertRaises(DeckError):
                read_pool(p, self.rules, self.required)

    def test_auto_packages_are_evidence_not_alias_pairs(self):
        self.assertTrue(self.packages)
        self.assertNotIn("auto-100-300", self.packages)
        self.assertTrue(all(not p.to_json()["combo_verified"] for p in self.packages.values()))

    def test_shared_package_counts_use_max_not_sum(self):
        a = apply_minima(empty_deck(), (("main", 100, 2),))
        b = apply_minima(a, (("main", 100, 1), ("main", 101, 1)))
        self.assertEqual(b["main"].count(100), 2)
        self.assertEqual(a["main"], [100, 100])

    def test_forced_package_and_dependency(self):
        supplied = self.package_payload()
        supplied["packages"].append({"id": "parent", "requires": ["bundle"], "evidence": "test",
                                     "members": [{"section": "main", "code": 102, "count": 3}]})
        packages = build_packages(self.candidates, self.rules, supplied)
        result = self.generate(packages=packages, forced=["parent"])
        for d in result["decks"]:
            self.assertGreaterEqual(d["main"].count(101), 2)
            self.assertGreaterEqual(d["main"].count(102), 3)
            self.assertIn(200, d["extra"])
            self.assertIn("bundle", d["selected_packages"])
            self.assertIn("parent", d["selected_packages"])

    def test_package_cycle_missing_dependency(self):
        for deps in (["bundle"], ["missing"]):
            with self.assertRaises(DeckError):
                build_packages(self.candidates, self.rules, self.package_payload(deps))

    def test_package_bad_member(self):
        for update in ({"code": 99999}, {"count": 4}, {"section": "side"}, {"code": 200}):
            supplied = self.package_payload()
            supplied["packages"][0]["members"][0].update(update)
            with self.assertRaises(DeckError):
                build_packages(self.candidates, self.rules, supplied)

    def test_package_dependency_aggregate_over_limit(self):
        supplied = self.package_payload()
        supplied["packages"][0]["members"] = [{"section": "main", "code": 100, "count": 3}]
        supplied["packages"].append({"id": "parent", "requires": ["bundle"], "evidence": "alias test",
                                     "members": [{"section": "main", "code": 300, "count": 1}]})
        with self.assertRaises(DeckError):
            build_packages(self.candidates, self.rules, supplied)

    def test_forced_package_extra_capacity_rejected(self):
        packages = build_packages(self.candidates, self.rules, self.package_payload())
        with self.assertRaises(DeckError):
            self.generate(replace(self.config, extra_size=0), packages=packages, forced=["bundle"])

    def test_broken_selected_package_rejected(self):
        packages = build_packages(self.candidates, self.rules, self.package_payload())
        with self.assertRaises(DeckError):
            check_packages(self.legal(), packages, ["bundle"])

    def test_empty_extra_no_optional_extra_leak(self):
        for d in self.generate(replace(self.config, extra_size=0))["decks"]:
            self.assertEqual(d["extra"], [])

    def test_required_extra_supported(self):
        required = {"main": {100: 2}, "extra": {200: 2}}
        result = generate_population(self.candidates, self.packages, self.rules, required, self.config)
        for d in result["decks"]:
            self.assertGreaterEqual(d["extra"].count(200), 2)

    def test_insufficient_capacity_is_error(self):
        candidates = {code: row for code, row in self.candidates.items() if 100 <= code <= 110}
        with self.assertRaisesRegex(DeckError, "insufficient capacity"):
            generate_population(candidates, {}, self.rules, self.required, self.config)

    def test_duplicate_population_exhaustion(self):
        profile = copy.deepcopy(self.profile)
        profile["default_limit"] = 1
        rules = RuleProfile(profile, self.catalog)
        candidates = {code: row for code, row in self.candidates.items() if 100 <= code <= 139}
        config = GenerationConfig(count=2, sizes=(40,), extra_size=0, max_packages=0, attempts_per_deck=3)
        with self.assertRaisesRegex(DeckError, "sampling budget exhausted"):
            generate_population(candidates, {}, rules, {"main": {100: 1}, "extra": {}}, config)

    def test_bad_generation_config(self):
        for update in ({"count": 0}, {"count": 1}, {"seed": -1}, {"sizes": (39,)},
                       {"sizes": (61,)}, {"sizes": ()}, {"sizes": (40, 40)}, {"extra_size": 16},
                       {"side_size": -1}, {"max_packages": 21}, {"attempts_per_deck": 0}):
            with self.assertRaises(DeckError):
                self.generate(replace(self.config, **update))

    def test_identity_ignores_order_but_preserves_alias_variants_and_sections(self):
        a = self.legal()
        b = copy.deepcopy(a); b["main"].reverse()
        self.assertEqual(deck_identity(a, self.catalog), deck_identity(b, self.catalog))
        b = copy.deepcopy(a); b["main"][0] = 300
        self.assertNotEqual(deck_identity(a, self.catalog), deck_identity(b, self.catalog))
        b = copy.deepcopy(a); b["side"] = [b["main"].pop()]
        self.assertNotEqual(deck_identity(a, self.catalog), deck_identity(b, self.catalog))

    def test_ydk_roundtrip_and_rejections(self):
        self.assertEqual(parse_ydk(ydk_text(self.legal())), self.legal())
        for text in ("100", "#extra\n200", "#main\n#main", "#main\n!bad", "#main\n0", "#main\n-1", ""):
            with self.assertRaises(DeckError):
                parse_ydk(text)

    def test_cli_parsing(self):
        self.assertEqual(parse_required(["100=2"]), {100: 2})
        self.assertEqual(parse_sizes("60,40:42"), (40, 41, 42, 60))
        for values in (["100:2"], ["100=0"], ["100=4"], ["100=2", "100=1"], ["-1=1"]):
            with self.assertRaises(DeckError):
                parse_required(values)
        for value in ("", "39:61", "60:40", "40,,41", "x"):
            with self.assertRaises(DeckError):
                parse_sizes(value)

    def test_cli_artifact_determinism_and_provenance(self):
        pool_path, rules_path = self.directory / "pool.json", self.directory / "rules.json"
        pool_path.write_text(json_text(self.payload)); rules_path.write_text(json_text(self.profile))
        for name in ("out-a", "out-b"):
            result = cli_main(["--db", str(self.db_path), "--pool", str(pool_path), "--rules", str(rules_path),
                               "--required-main", "100=2", "--sizes", "40,50,60", "--count", "6",
                               "--output", str(self.directory / name)])
            self.assertEqual(result, 0)
        a, b = self.directory / "out-a", self.directory / "out-b"
        for path in a.rglob("*"):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (b / path.relative_to(a)).read_bytes())
        payload = read_json(a / "population.json")
        self.assertFalse(payload["tournament_legality_verified"])
        self.assertFalse(payload["win_rate_evaluated"])
        self.assertIn("database", payload["input_sha256"])
        self.assertEqual(len(payload["decks"]), 6)

    def test_output_not_overwritten(self):
        output = self.directory / "existing"
        output.mkdir()
        (output / "sentinel").write_text("keep me")
        with self.assertRaises(DeckError):
            write_population(output, {}, {}, {})
        self.assertEqual((output / "sentinel").read_text(), "keep me")

    def test_failed_run_does_not_publish_population(self):
        pool_path, rules_path = self.directory / "pool.json", self.directory / "rules.json"
        self.profile["limits"] = {"100": 0}
        pool_path.write_text(json_text(self.payload)); rules_path.write_text(json_text(self.profile))
        output = self.directory / "failed"
        result = cli_main(["--db", str(self.db_path), "--pool", str(pool_path), "--rules", str(rules_path),
                           "--required-main", "100=2", "--output", str(output)])
        self.assertEqual(result, 2)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Phase4Tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f"PHASE4 UNIT PASS: {result.testsRun} tests (synthetic DB; no duels)")
        print(f"Generated population entries checked in property tests: {Phase4Tests.generated_decks}")
    raise SystemExit(0 if result.wasSuccessful() else 1)
