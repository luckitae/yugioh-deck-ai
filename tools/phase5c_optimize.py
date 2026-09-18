#!/usr/bin/env python3
"""Phase 5-C: 실제 OCGCore 반복 듀얼 승률을 1순위 Fitness로 사용하는 GA.

상대 Pool은 manifest의 split(training/validation/final)로 분리한다. 현재 policy는
``first-legal-v1`` baseline이므로 결과는 해당 policy/opponent snapshot에 대한 실제 승률이며
최종 인간 수준 성능이나 공식 메타 승률이라고 주장하지 않는다.
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from deck.packages import check_packages, read_pool
from deck.rules import CardCatalog, DeckError, RuleProfile, SECTIONS, json_text, parse_ydk, read_json, sha256, ydk_text
from search.duel_fitness import DuelEvaluator, DuelFitnessError, DuelSchedule, load_opponent_pool, parse_seeds
from search.ga import OPERATIONS, SearchConfig, run_search
from tools.phase5_optimize import load_packages, parse_required

VERSION = "phase5c-real-duel-ga-v1"


def parse_operations(text: str) -> tuple[str, ...]:
    if not isinstance(text, str) or not text.strip():
        raise DeckError("mutation-ops cannot be empty")
    values = tuple(part.strip() for part in text.split(",") if part.strip())
    if not values or len(set(values)) != len(values) or any(value not in OPERATIONS for value in values):
        raise DeckError("mutation-ops must be a unique comma-separated subset of supported operations")
    return values


def safe_source_decks(search_dir: Path, payload: dict, count: int) -> list[dict]:
    rows = payload.get("decks")
    if not isinstance(rows, list) or len(rows) < count:
        raise DeckError("Phase 5-A search has too few decks")
    out: list[dict] = []
    for row in rows[:count]:
        if not isinstance(row, dict):
            raise DeckError("Phase 5-A deck row must be an object")
        relative = Path(row.get("file", ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise DeckError("unsafe Phase 5-A deck path")
        path = search_dir / relative
        if not path.is_file():
            raise DeckError(f"missing Phase 5-A deck: {relative}")
        parsed = parse_ydk(path.read_text(encoding="utf-8"))
        for section in SECTIONS:
            if parsed[section] != row.get(section):
                raise DeckError("Phase 5-A YDK/manifest mismatch")
        selected = row.get("selected_packages", [])
        if (not isinstance(selected, list) or any(not isinstance(pid, str) for pid in selected) or
                len(selected) != len(set(selected))):
            raise DeckError("Phase 5-A selected_packages invalid/duplicate")
        out.append({**parsed, "selected_packages": sorted(selected)})
    return out


def validate_opponents(opponents, rules: RuleProfile) -> None:
    for opponent in opponents:
        deck = parse_ydk(opponent.file.read_text(encoding="utf-8"))
        rules.check(deck)


def write_output(staging: Path, result: dict, evaluator: DuelEvaluator, metadata: dict,
                 rules: RuleProfile, required: dict[str, dict[int, int]]) -> None:
    (staging / "decks").mkdir(exist_ok=True)
    rows = []
    for index, item in enumerate(result["population"]):
        deck = {section: item[section] for section in SECTIONS}
        relative = f"decks/{index:04d}_{item['deck_id'][:16]}.ydk"
        text = ydk_text(deck).replace(
            "#created by yugioh-deck-ai phase4; NOT a win-rate result",
            "#created by yugioh-deck-ai phase5-c; baseline-policy win-rate evaluated", 1,
        )
        (staging / relative).write_text(text, encoding="utf-8", newline="\n")
        metrics = dict(item["metrics"])
        if isinstance(metrics.get("evaluation_file"), str):
            metrics["evaluation_file"] = "duel_eval/" + metrics["evaluation_file"]
        rows.append({
            "rank": index + 1,
            "deck_id": item["deck_id"],
            "file": relative,
            "main": item["main"], "extra": item["extra"], "side": item["side"],
            "selected_packages": item["selected_packages"],
            "origin": item.get("origin", "unknown"),
            "parent_deck_id": item.get("parent_deck_id"),
            "mutation": item.get("mutation"),
            "metrics": metrics,
        })
    if not rows or not rows[0]["metrics"].get("win_rate_evaluated"):
        raise DeckError("no fully evaluated best deck; cannot publish a real-win-rate result")
    complete_final = sum(bool(row["metrics"].get("win_rate_evaluated")) for row in rows)
    manifest = {
        **metadata,
        "status": "duel-optimized",
        "duel_evaluated": True,
        "win_rate_evaluated": complete_final == len(rows),
        "best_win_rate_evaluated": True,
        "fitness_kind": "real-ocgcore-win-rate-v1",
        "fitness_primary": "actual_win_rate_ppm",
        "policy": "first-legal-v1",
        "history": result["history"],
        "operation_counts": result["operation_counts"],
        "mutation_failures": result["mutation_failures"],
        "actual_engine_duels": evaluator.runner_invocations,
        "unique_evaluated_decks": len(evaluator.cache),
        "complete_final_decks": complete_final,
        "incomplete_final_decks": len(rows) - complete_final,
        "decks": rows,
    }
    (staging / "search.json").write_text(json_text(manifest), encoding="utf-8", newline="\n")
    best = rows[0]["metrics"]
    (staging / "SUMMARY.txt").write_text(
        f"Phase 5-C final population: {len(rows)}\n"
        f"Actual OCGCore runner invocations: {evaluator.runner_invocations}\n"
        f"Best actual win rate ppm: {best['win_rate_ppm']}\n"
        f"Opponent pool: {metadata['opponent_pool']['id']} / split={metadata['opponent_pool']['split']}\n"
        f"Policy: first-legal-v1 baseline\n"
        f"Complete final schedules: {complete_final}/{len(rows)}\n"
        "Fitness primary signal: actual OCGCore win rate.\n"
        "This is NOT an official/meta-certified win rate and the baseline policy is not a strong AI.\n",
        encoding="utf-8", newline="\n",
    )
    # 마지막으로 모든 최종 덱 제약을 재검사한다.
    for row in rows:
        rules.check({section: row[section] for section in SECTIONS}, required)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--scripts", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--search", type=Path, required=True, help="Phase 5-A search directory")
    parser.add_argument("--pool", type=Path, required=True, help="Phase 3 candidate pool JSON")
    parser.add_argument("--packages", type=Path, required=True, help="Phase 4 packages.json")
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--opponents", type=Path, required=True, help="opponent pool manifest JSON")
    parser.add_argument("--split", choices=("training", "validation", "final"), default="training")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--population-size", type=int, default=8)
    parser.add_argument("--generations", type=int, default=2)
    parser.add_argument("--elite", type=int, default=2)
    parser.add_argument("--tournament", type=int, default=3)
    parser.add_argument("--mutation-attempts", type=int, default=120)
    parser.add_argument("--search-seed", type=int, default=1)
    parser.add_argument("--duel-seeds", default="1,42")
    parser.add_argument("--mutation-ops", default=",".join(OPERATIONS))
    parser.add_argument("--max-calls", type=int, default=200000)
    parser.add_argument("--duel-timeout", type=int, default=90)
    args = parser.parse_args(argv)

    staging: Path | None = None
    try:
        if args.output.exists():
            raise DeckError("output already exists")
        search_path = args.search / "search.json"
        if not search_path.is_file():
            raise DeckError("Phase 5-A search.json missing")
        search = read_json(search_path)
        if (not isinstance(search, dict) or search.get("schema") != 1 or search.get("status") != "prescreened" or
                search.get("duel_evaluated") is not False or search.get("win_rate_evaluated") is not False):
            raise DeckError("unsupported Phase 5-A provenance")
        catalog = CardCatalog(args.db)
        rules = RuleProfile(read_json(args.rules), catalog)
        required = parse_required(search)
        candidates, excluded = read_pool(read_json(args.pool), rules, required)
        packages = load_packages(args.packages, candidates, rules)
        hashes = search.get("input_sha256")
        if not isinstance(hashes, dict):
            raise DeckError("Phase 5-A input hashes missing")
        expected = {
            "database": sha256(args.db), "candidate_pool": sha256(args.pool),
            "packages": sha256(args.packages), "rules": sha256(args.rules),
        }
        if any(hashes.get(key) != value for key, value in expected.items()):
            raise DeckError("Phase 5-A provenance does not match DB/pool/packages/rules")
        pool_payload, opponents = load_opponent_pool(args.opponents, args.split)
        validate_opponents(opponents, rules)
        seeds = parse_seeds(args.duel_seeds)
        schedule = DuelSchedule(seeds, args.max_calls, args.duel_timeout)
        operations = parse_operations(args.mutation_ops)
        config = SearchConfig(args.population_size, args.generations, args.elite,
                              args.tournament, args.mutation_attempts, args.search_seed)
        config.validate()
        initial = safe_source_decks(args.search, search, config.population_size)
        for row in initial:
            rules.check({section: row[section] for section in SECTIONS}, required)
            check_packages({section: row[section] for section in SECTIONS}, packages, row["selected_packages"])

        args.output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".phase5c-", dir=args.output.parent))
        evaluator = DuelEvaluator(args.runner, args.db, args.scripts, opponents, schedule, required,
                                  staging / "duel_eval")
        result = run_search(initial, candidates, packages, rules, required, evaluator, config, operations)
        metadata = {
            "schema": 1,
            "optimizer": VERSION,
            "python_version": platform.python_version(),
            "search_config": asdict(config),
            "mutation_operations": list(operations),
            "duel_schedule": {"seeds": list(seeds), "seats": [0, 1],
                              "max_calls": schedule.max_calls, "timeout_seconds": schedule.timeout_seconds},
            "required": {section: {str(code): count for code, count in sorted(required[section].items())}
                         for section in ("main", "extra")},
            "opponent_pool": {"id": pool_payload["id"], "kind": pool_payload["kind"],
                              "split": args.split, "opponents": [row.id for row in opponents],
                              "manifest_sha256": sha256(args.opponents),
                              "deck_sha256": {row.id: sha256(row.file) for row in opponents}},
            "input_sha256": {
                "database": sha256(args.db), "phase5a_search": sha256(search_path),
                "candidate_pool": sha256(args.pool), "packages": sha256(args.packages),
                "rules": sha256(args.rules), "opponents": sha256(args.opponents),
                "runner": sha256(args.runner), "phase2_lock": sha256(ROOT / "data/phase2.lock.json"),
            },
            "excluded_candidates": excluded,
            "source_phase5a_decks_considered": len(initial),
        }
        write_output(staging, result, evaluator, metadata, rules, required)
        if args.output.exists():
            raise DeckError("output appeared while optimizing; refusing to overwrite")
        staging.rename(args.output)
        staging = None
        payload = read_json(args.output / "search.json")
        best = payload["decks"][0]["metrics"]["win_rate_ppm"]
        print(f"PHASE5-C OPTIMIZE PASS: population={len(payload['decks'])} actual_duels={payload['actual_engine_duels']} best_win_rate_ppm={best}")
        print("REAL OCGCore WIN-RATE FITNESS; baseline policy/opponent snapshot, NOT final meta certification")
        return 0
    except (OSError, ValueError, KeyError, TypeError, DeckError, DuelFitnessError) as error:
        print(f"PHASE5-C OPTIMIZE FAIL: {error}", file=sys.stderr)
        return 2
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    raise SystemExit(main())
