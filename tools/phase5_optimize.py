#!/usr/bin/env python3
"""Phase 5-A: Phase 4 population을 deterministic 저비용 지표로 선별/변이한다.

실제 듀얼 승률 evaluator가 아니다. 출력에는 이를 명시적으로 기록한다.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import platform
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from deck.packages import Package, package_closure, read_pool
from deck.rules import CardCatalog, DeckError, RuleProfile, json_text, read_json, sha256, ydk_text
from search.fitness import LowCostWeights, low_cost_evaluate
from search.ga import SearchConfig, run_search

VERSION = "phase5-lowcost-ga-v1"


def parse_required(payload: dict) -> dict[str, dict[int, int]]:
    required = payload.get("required")
    if not isinstance(required, dict) or set(required) != {"main", "extra"}:
        raise DeckError("population required block missing/invalid")
    out: dict[str, dict[int, int]] = {"main": {}, "extra": {}}
    for section in out:
        counts = required[section]
        if not isinstance(counts, dict):
            raise DeckError("population required counts invalid")
        for text, count in counts.items():
            if not isinstance(text, str) or not text.isascii() or not text.isdecimal():
                raise DeckError("required card IDs must be decimal strings")
            code = int(text)
            if code <= 0 or type(count) is not int or not 1 <= count <= 3 or code in out[section]:
                raise DeckError("invalid required card/count")
            out[section][code] = count
    return out


def load_packages(path: Path, candidates: dict[int, dict], rules: RuleProfile) -> dict[str, Package]:
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get("schema") != 1 or set(payload) != {"schema", "packages"}:
        raise DeckError("packages manifest: unsupported schema")
    rows = payload["packages"]
    if not isinstance(rows, list) or len(rows) > 10000:
        raise DeckError("packages manifest: invalid list")
    packages: dict[str, Package] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise DeckError("packages manifest: package must be object")
        expected = {"id", "members", "requires", "evidence", "origin", "combo_verified"}
        if set(row) != expected or row["combo_verified"] is not False:
            raise DeckError("packages manifest: invalid fields/verification flag")
        pid = row["id"]
        if not isinstance(pid, str) or not pid or pid in packages:
            raise DeckError("packages manifest: invalid/duplicate id")
        members = []
        for member in row["members"]:
            if not isinstance(member, dict) or set(member) != {"section", "code", "count"}:
                raise DeckError("packages manifest: invalid member")
            section, code, count = member["section"], member["code"], member["count"]
            if section not in ("main", "extra") or type(code) is not int or code not in candidates:
                raise DeckError("packages manifest: member outside eligible pool")
            if type(count) is not int or not 1 <= count <= 3:
                raise DeckError("packages manifest: invalid count")
            if rules.catalog[code].section != section:
                raise DeckError("packages manifest: wrong member section")
            members.append((section, code, count))
        requires = row["requires"]
        if not isinstance(requires, list) or any(not isinstance(x, str) for x in requires):
            raise DeckError("packages manifest: invalid dependencies")
        if not isinstance(row["evidence"], str) or not isinstance(row["origin"], str):
            raise DeckError("packages manifest: invalid text")
        packages[pid] = Package(pid, tuple(sorted(members)), tuple(sorted(requires)), row["evidence"], row["origin"])
    for pid in packages:
        package_closure(packages, [pid])
    return dict(sorted(packages.items()))


def parse_weights(path: Path) -> LowCostWeights:
    payload = read_json(path)
    if not isinstance(payload, dict) or set(payload) != {"schema", "id", "kind", "weights", "note"}:
        raise DeckError("fitness config: invalid fields")
    if payload["schema"] != 1 or payload["kind"] != "prescreen-not-winrate":
        raise DeckError("fitness config: unsupported schema/kind")
    weights = payload["weights"]
    if not isinstance(weights, dict) or set(weights) != {"required_access", "relation_quality"}:
        raise DeckError("fitness config: invalid weights")
    result = LowCostWeights(weights["required_access"], weights["relation_quality"])
    result.validate()
    return result


def write_output(output: Path, result: dict, metadata: dict, rules: RuleProfile) -> None:
    if output.exists():
        raise DeckError(f"output already exists (will not overwrite): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".phase5-", dir=output.parent))
    try:
        (staging / "decks").mkdir()
        rows = []
        for index, item in enumerate(result["population"]):
            deck = {section: item[section] for section in ("main", "extra", "side")}
            relative = f"decks/{index:04d}_{item['deck_id'][:16]}.ydk"
            (staging / relative).write_text(ydk_text(deck).replace("#created by yugioh-deck-ai phase4; NOT a win-rate result", "#created by yugioh-deck-ai phase5-a; NOT a win-rate result", 1), encoding="utf-8", newline="\n")
            rows.append({
                "rank": index + 1,
                "deck_id": item["deck_id"],
                "file": relative,
                "main": item["main"], "extra": item["extra"], "side": item["side"],
                "selected_packages": item["selected_packages"],
                "origin": item.get("origin", "unknown"),
                "parent_deck_id": item.get("parent_deck_id"),
                "mutation": item.get("mutation"),
                "metrics": item["metrics"],
            })
        manifest = {
            **metadata,
            "status": "prescreened",
            "duel_evaluated": False,
            "win_rate_evaluated": False,
            "fitness_kind": "low-cost-prescreen-not-winrate",
            "history": result["history"],
            "operation_counts": result["operation_counts"],
            "mutation_failures": result["mutation_failures"],
            "decks": rows,
        }
        (staging / "search.json").write_text(json_text(manifest), encoding="utf-8", newline="\n")
        (staging / "SUMMARY.txt").write_text(
            f"Phase 5-A population: {len(rows)}\n"
            f"Best prescreen score ppm: {rows[0]['metrics']['score_ppm']}\n"
            "Actual engine duels: 0\n"
            "Win rate: NOT EVALUATED\n"
            "This score is only a low-cost prescreen for later duel evaluation.\n",
            encoding="utf-8", newline="\n")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--population", type=Path, required=True, help="Phase 4 population directory")
    parser.add_argument("--pool", type=Path, required=True, help="Phase 3 candidate pool JSON")
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--fitness", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--population-size", type=int, default=48)
    parser.add_argument("--generations", type=int, default=4)
    parser.add_argument("--elite", type=int, default=8)
    parser.add_argument("--tournament", type=int, default=4)
    parser.add_argument("--mutation-attempts", type=int, default=80)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise DeckError("output already exists")
        population_path = args.population / "population.json"
        packages_path = args.population / "packages.json"
        if not population_path.is_file() or not packages_path.is_file():
            raise DeckError("Phase 4 population.json/packages.json missing")
        population = read_json(population_path)
        if not isinstance(population, dict) or population.get("schema") != 1 or population.get("status") != "generated":
            raise DeckError("unsupported Phase 4 population")
        if population.get("win_rate_evaluated") is not False:
            raise DeckError("Phase 4 provenance flag mismatch")
        catalog = CardCatalog(args.db)
        rules = RuleProfile(read_json(args.rules), catalog)
        required = parse_required(population)
        candidates, excluded = read_pool(read_json(args.pool), rules, required)
        packages = load_packages(packages_path, candidates, rules)
        hashes = population.get("input_sha256")
        if not isinstance(hashes, dict) or hashes.get("database") != sha256(args.db) or hashes.get("rules") != sha256(args.rules):
            raise DeckError("Phase 4 population provenance does not match DB/rules")
        if hashes.get("candidate_pool") != sha256(args.pool):
            raise DeckError("Phase 4 population provenance does not match candidate pool")
        initial = population.get("decks")
        if not isinstance(initial, list):
            raise DeckError("Phase 4 population decks missing")
        weights = parse_weights(args.fitness)
        config = SearchConfig(args.population_size, args.generations, args.elite,
                              args.tournament, args.mutation_attempts, args.seed)
        evaluator = lambda deck: low_cost_evaluate(deck, candidates, required, weights)
        result = run_search(initial, candidates, packages, rules, required, evaluator, config)
        metadata = {
            "schema": 1,
            "optimizer": VERSION,
            "python_version": platform.python_version(),
            "search_config": asdict(config),
            "weights": asdict(weights),
            "required": {s: {str(code): count for code, count in sorted(required[s].items())} for s in required},
            "input_sha256": {
                "database": sha256(args.db), "population": sha256(population_path),
                "candidate_pool": sha256(args.pool), "packages": sha256(packages_path),
                "rules": sha256(args.rules), "fitness": sha256(args.fitness),
            },
            "excluded_candidates": excluded,
            "source_population_size": len(initial),
            "rules": rules.payload,
        }
        write_output(args.output, result, metadata, rules)
        best = result["population"][0]["metrics"]["score_ppm"]
        print(f"PHASE5-A OPTIMIZE PASS: population={len(result['population'])} generations={config.generations} best_score_ppm={best}")
        print("NO DUELS; NOT A WIN-RATE RESULT")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"PHASE5-A OPTIMIZE FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
