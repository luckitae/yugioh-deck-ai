#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from deck.experiment import (
    allowed_set_sha256,
    allowed_set_text,
    build_allowed_set,
    check_allowed_deck,
    load_experiment,
    load_prepared_experiment,
)
from deck.generator import GenerationConfig, generate_population
from deck.packages import Package, build_packages, read_pool
from deck.rules import CardCatalog, DeckError, RuleProfile, SECTIONS, json_text, sha256, ydk_text
from search.duel_fitness import DuelEvaluator, DuelFitnessError, DuelSchedule, Opponent, _deck_fingerprint
from search.ga import SearchConfig, mutate_once, run_search
from tools.phase5c_optimize import validate_opponents

checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    if not condition:
        raise AssertionError(message)
    checks += 1


def expect(error_type, function, contains: str) -> None:
    global checks
    try:
        function()
    except error_type as error:
        if contains not in str(error):
            raise AssertionError(f"expected {contains!r}, got {error!r}") from error
        checks += 1
        return
    raise AssertionError(f"expected {error_type.__name__}: {contains}")


def make_db(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE datas(id INTEGER PRIMARY KEY,ot INTEGER,alias INTEGER,setcode INTEGER,"
        "type INTEGER,atk INTEGER,def INTEGER,level INTEGER,race INTEGER,attribute INTEGER,category INTEGER);"
        "CREATE TABLE texts(id INTEGER PRIMARY KEY,name TEXT,desc TEXT);"
    )
    rows = [(100, 0x11, "Normal"), (101, 0x21, "Required Effect"),
            (102, 0x1000021, "Pendulum"), (103, 0x2, "Spell"), (104, 0x4, "Trap")]
    rows += [(code, 0x21, f"Effect {code}") for code in range(110, 130)]
    rows += [(200, 0x41, "Fusion")]
    for code, kind, name in rows:
        db.execute("INSERT INTO datas VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (code, 3, 0, 0, kind, 0, 0, 4, 1, 1, 0))
        db.execute("INSERT INTO texts VALUES(?,?,?)", (code, name, ""))
    db.commit()
    db.close()


def write_spec(path: Path, required: int = 101, exceptions: list[int] | None = None) -> None:
    path.write_text(json.dumps({
        "schema": 1,
        "deck": {
            "required": [{"code": required, "section": "main", "min": 1, "max": 2}],
            "main": {"min": 40, "max": 40},
            "extra": {"min": 0, "max": 0},
            "side": {"min": 0, "max": 0},
        },
        "candidate_filter": {
            "exclude_normal_monsters": True,
            "exclude_pendulum": True,
            "exceptions": exceptions or [],
        },
    }), encoding="utf-8")


def candidate_row(code: int, pool: str) -> dict:
    return {
        "code": code,
        "pool": pool,
        "score": 1000 - (code % 100),
        "relations": [{
            "required_code": 101,
            "strength": "STRONG",
            "kind": "UNIT",
            "detail": "R1 unit evidence",
        }],
    }


def make_pool() -> dict:
    codes = [100, 101, 102, 103, 104] + list(range(110, 130))
    return {
        "schema": 1,
        "analysis_profile": "phase3-text-metadata-v1",
        "required": [101],
        "candidates": [
            candidate_row(code, "REQUIRED" if code == 101 else ("ENGINE" if code % 2 == 0 else "GENERIC"))
            for code in codes
        ],
    }


def write_prepared(directory: Path, spec_path: Path, spec, allowed: list[int],
                   db_path: Path, rules_path: Path) -> None:
    directory.mkdir()
    text = allowed_set_text(allowed)
    digest = allowed_set_sha256(allowed)
    (directory / "allowed_ids.txt").write_text(text, encoding="ascii", newline="\n")
    manifest = {
        "schema": 1,
        "experiment_id": spec.experiment_id,
        "normalized_spec": spec.normalized,
        "allowed_set": {"count": len(allowed), "sha256": digest, "file": "allowed_ids.txt"},
        "input_sha256": {
            "spec": sha256(spec_path),
            "database": sha256(db_path),
            "rules": sha256(rules_path),
        },
    }
    (directory / "experiment.normalized.json").write_text(json_text(manifest), encoding="utf-8")


def main() -> int:
    global checks
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        db_path = root / "cards.cdb"
        make_db(db_path)
        rules_path = root / "rules.json"
        rules_payload = {
            "schema": 1, "id": "r1-unit", "kind": "test-only", "scope_mask": 3,
            "default_limit": 3, "limits": {}, "source": "unit", "note": "unit",
        }
        rules_path.write_text(json_text(rules_payload), encoding="utf-8")
        catalog = CardCatalog(db_path)
        rules = RuleProfile(rules_payload, catalog)

        spec_path = root / "spec.json"
        write_spec(spec_path)
        spec = load_experiment(spec_path, catalog, rules)
        allowed_list = build_allowed_set(spec, catalog, rules)
        allowed = frozenset(allowed_list)
        check(100 not in allowed, "normal monster excluded")
        check(102 not in allowed, "pendulum excluded")
        check(101 in allowed and 103 in allowed and 104 in allowed, "eligible cards retained")
        check(len(spec.experiment_id) == 64, "stable experiment id")

        bad_spec = root / "bad.json"
        write_spec(bad_spec, 100)
        expect(DeckError, lambda: load_experiment(bad_spec, catalog, rules), "conflicts")
        exception_spec = root / "exception.json"
        write_spec(exception_spec, 100, [100])
        exception = load_experiment(exception_spec, catalog, rules)
        check(100 in build_allowed_set(exception, catalog, rules), "explicit exception works")
        typo = json.loads(spec_path.read_text(encoding="utf-8"))
        typo["typo"] = 1
        typo_path = root / "typo.json"
        typo_path.write_text(json.dumps(typo), encoding="utf-8")
        expect(DeckError, lambda: load_experiment(typo_path, catalog, rules), "missing/unknown")

        prepared_dir = root / "prepared"
        write_prepared(prepared_dir, spec_path, spec, allowed_list, db_path, rules_path)
        prepared = load_prepared_experiment(prepared_dir, catalog, rules, db_path, rules_path)
        check(prepared.allowed_codes == allowed and prepared.spec.experiment_id == spec.experiment_id,
              "prepared allowed set round trip")
        original_allowed_text = (prepared_dir / "allowed_ids.txt").read_text(encoding="ascii")
        (prepared_dir / "allowed_ids.txt").write_text(original_allowed_text + "100\n", encoding="ascii")
        expect(DeckError, lambda: load_prepared_experiment(prepared_dir, catalog, rules, db_path, rules_path),
               "file hash mismatch")
        (prepared_dir / "allowed_ids.txt").write_text(original_allowed_text, encoding="ascii")

        required = spec.required_minima()
        payload = make_pool()
        candidates, excluded = read_pool(payload, rules, required, allowed)
        check(100 not in candidates and 102 not in candidates, "stale Phase 3 pool is re-filtered")
        check({row["code"] for row in excluded if row["reason"] == "experiment_filter"} == {100, 102},
              "filter exclusions are diagnosed")

        explicit_bad_package = {
            "schema": 1,
            "packages": [{
                "id": "bad", "members": [{"section": "main", "code": 100, "count": 1}],
                "requires": [], "evidence": "unit",
            }],
        }
        expect(DeckError,
               lambda: build_packages(candidates, rules, explicit_bad_package, allowed),
               "outside eligible pool")

        contaminated_candidates = dict(candidates)
        contaminated_candidates[100] = candidate_row(100, "ENGINE")
        config = GenerationConfig(count=2, sizes=(40,), seed=7, extra_size=0, side_size=0,
                                  max_packages=0, attempts_per_deck=200)
        expect(DeckError,
               lambda: generate_population(contaminated_candidates, {}, rules, required, config,
                                           allowed_codes=allowed, experiment=spec),
               "outside experiment allowed set")

        generated = generate_population(candidates, {}, rules, required, config,
                                        allowed_codes=allowed, experiment=spec)
        check(len(generated["decks"]) == 2, "valid initial population generated")
        check(all(deck["main"].count(101) <= 2 for deck in generated["decks"]),
              "required maximum enforced during generation")
        check(all(code in allowed for deck in generated["decks"] for section in SECTIONS for code in deck[section]),
              "initial population stays inside allowed set")

        parent = generated["decks"][0]
        mutation_candidates = dict(candidates)
        mutation_candidates[100] = candidate_row(100, "ENGINE")
        import random
        for seed in range(30):
            child = mutate_once(parent, "replace_card", mutation_candidates, {}, rules, required,
                                random.Random(seed), allowed, spec)
            if child is not None:
                check(all(code in allowed for section in SECTIONS for code in child[section]),
                      "replace mutation cannot reintroduce forbidden card")
                break
        else:
            raise AssertionError("replace mutation produced no child in 30 deterministic attempts")

        bad_package = {"bad": Package("bad", (("main", 100, 1),), (), "unit", "unit")}
        child = mutate_once(parent, "package_add", candidates, bad_package, rules, required,
                            random.Random(1), allowed, spec)
        check(child is None, "package mutation rejects forbidden member")

        bad_initial = copy.deepcopy(parent)
        replace_index = next(i for i, code in enumerate(bad_initial["main"]) if code != 101)
        bad_initial["main"][replace_index] = 100
        bad_initial["main"].sort()
        rules.check({section: bad_initial[section] for section in SECTIONS}, required)
        evaluator = lambda deck: {"score_ppm": 1}
        search_config = SearchConfig(population_size=2, generations=1, elite_count=1,
                                     tournament_size=2, mutation_attempts=20, seed=1)
        expect(DeckError,
               lambda: run_search([bad_initial, generated["decks"][1]], candidates, {}, rules,
                                  required, evaluator, search_config,
                                  allowed_codes=allowed, experiment=spec),
               "invalid initial individual")

        expect(DeckError,
               lambda: spec.check_deck({section: bad_initial[section] for section in SECTIONS}, catalog, rules),
               "outside experiment allowed set")
        expect(DeckError,
               lambda: check_allowed_deck({section: bad_initial[section] for section in SECTIONS}, allowed,
                                          "final output"),
               "outside experiment allowed set")

        runner = root / "runner"
        runner.write_text("dummy", encoding="utf-8")
        scripts = root / "scripts"
        scripts.mkdir()
        opponent_path = root / "opponent.ydk"
        opponent_deck = {section: list(parent[section]) for section in SECTIONS}
        opponent_deck["main"][0] = 100
        opponent_deck["main"].sort()
        opponent_path.write_text(ydk_text(opponent_deck), encoding="utf-8")
        opponent = Opponent("opponent", opponent_path, ("training",), "unit")
        validate_opponents([opponent], rules)
        check(True, "candidate filter is not applied to opponent deck")

        duel = DuelEvaluator(runner, db_path, scripts, [opponent], DuelSchedule((1,), 10, 1),
                             required, root / "eval", allowed)
        invalid_deck = {section: list(bad_initial[section]) for section in SECTIONS}
        duel.cache[_deck_fingerprint(invalid_deck)] = {"score_ppm": 1_000_000}
        expect(DuelFitnessError, lambda: duel(invalid_deck), "outside experiment allowed set")
        check(duel.runner_invocations == 0, "forbidden cached deck rejected before runner/cache use")

    print(f"R1 UNIT PASS: {checks} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
