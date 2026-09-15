#!/usr/bin/env python3
"""Phase 5-A 실제 고정 DB/Phase 4 산출물 통합 검사. 실제 엔진 듀얼은 아직 실행하지 않는다."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ART4 = ROOT / "artifacts/phase4"
ART5 = ROOT / "artifacts/phase5"
DB = ROOT / "data/vendor/BabelCDB/cards.cdb"
RULES = ROOT / "data/rules/phase4-test-no-banlist.json"
FITNESS = ROOT / "data/search/phase5-lowcost-v1.json"
POOL = ART4 / "single_pool.json"
SOURCE = ART4 / "population_a"
OPTIMIZER = ROOT / "tools/phase5_optimize.py"
VALIDATOR = ROOT / "phase4_validate"


def sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hashes(directory: Path) -> dict[str, str]:
    return {str(p.relative_to(directory)): sha256(p) for p in sorted(directory.rglob("*")) if p.is_file()}


def run(name: str, command: list[str], expect_ok: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=180)
    (ART5 / f"{name}.log").write_text(result.stdout, encoding="utf-8")
    if (result.returncode == 0) != expect_ok:
        raise RuntimeError(f"{name}: unexpected exit={result.returncode}\n{result.stdout}")
    return result


def optimize(name: str, seed: int = 77, population_size: int = 48,
             fitness: Path = FITNESS, population: Path = SOURCE, pool: Path = POOL,
             expect_ok: bool = True) -> Path:
    output = ART5 / name
    command = [sys.executable, str(OPTIMIZER), "--db", str(DB), "--population", str(population),
               "--pool", str(pool), "--rules", str(RULES), "--fitness", str(fitness),
               "--output", str(output), "--population-size", str(population_size),
               "--generations", "4", "--elite", "8", "--tournament", "4",
               "--mutation-attempts", "120", "--seed", str(seed)]
    run(name, command, expect_ok)
    if not expect_ok and output.exists():
        raise RuntimeError("failed optimization exposed an output directory")
    return output


def validate_output(directory: Path) -> dict:
    payload = json.loads((directory / "search.json").read_text(encoding="utf-8"))
    if payload.get("status") != "prescreened" or payload.get("fitness_kind") != "low-cost-prescreen-not-winrate":
        raise RuntimeError("wrong Phase 5-A status/kind")
    if payload.get("duel_evaluated") is not False or payload.get("win_rate_evaluated") is not False:
        raise RuntimeError("low-cost result presented as duel/win-rate evaluated")
    decks = payload.get("decks")
    if not isinstance(decks, list) or len(decks) != 48:
        raise RuntimeError("search population size mismatch")
    ids = [row["deck_id"] for row in decks]
    if len(set(ids)) != len(ids):
        raise RuntimeError("duplicate final deck identity")
    scores = [row["metrics"]["score_ppm"] for row in decks]
    if scores != sorted(scores, reverse=True):
        raise RuntimeError("final population not ranked by prescreen score")
    history = payload.get("history")
    if not isinstance(history, list) or len(history) != 5:
        raise RuntimeError("generation history mismatch")
    if any(history[i + 1]["best_score_ppm"] < history[i]["best_score_ppm"] for i in range(len(history) - 1)):
        raise RuntimeError("elitism regression")
    if sum(payload.get("operation_counts", {}).values()) <= 0:
        raise RuntimeError("no accepted mutations")
    if "NOT EVALUATED" not in (directory / "SUMMARY.txt").read_text(encoding="utf-8"):
        raise RuntimeError("summary lacks no-win-rate warning")

    source = json.loads((SOURCE / "population.json").read_text(encoding="utf-8"))
    required = source["required"]["main"]
    command = [str(VALIDATOR), "--db", str(DB)]
    for code, count in sorted(required.items(), key=lambda kv: int(kv[0])):
        command += ["--required-main", f"{code}={count}"]
    for row in decks:
        relative = Path(row["file"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("unsafe deck path")
        path = directory / relative
        if not path.is_file():
            raise RuntimeError("missing output YDK")
        command += ["--deck", str(path)]
    run(directory.name + "_cpp_validation", command)
    print(f"PASS {directory.name}: 48 unique legal decks, 5 generations including generation 0, C++ validation")
    return payload


def main() -> int:
    ART5.mkdir(parents=True, exist_ok=True)
    try:
        if not all(path.is_file() for path in (DB, RULES, FITNESS, POOL, OPTIMIZER, VALIDATOR,
                                                SOURCE / "population.json", SOURCE / "packages.json")):
            raise RuntimeError("Phase 2/3/4 prerequisites missing")
        first = optimize("search_a")
        a = validate_output(first)
        second = optimize("search_b")
        validate_output(second)
        if tree_hashes(first) != tree_hashes(second):
            raise RuntimeError("same inputs/seed did not produce byte-identical Phase 5-A artifacts")
        print("PASS repeat: byte-identical Phase 5-A artifacts")

        other = optimize("search_seed42", seed=42)
        b = validate_output(other)
        if [d["deck_id"] for d in a["decks"]] == [d["deck_id"] for d in b["decks"]]:
            raise RuntimeError("different seed did not alter final population")
        print("PASS seed sensitivity: seed 77 and 42 produced different final populations")

        bad_fitness = ART5 / "bad_fitness.json"
        bad = json.loads(FITNESS.read_text(encoding="utf-8"))
        bad["weights"]["relation_quality"] = 301
        bad_fitness.write_text(json.dumps(bad, sort_keys=True), encoding="utf-8")
        optimize("reject_bad_weights", fitness=bad_fitness, expect_ok=False)
        optimize("reject_oversized_population", population_size=101, expect_ok=False)

        stale_dir = ART5 / "stale_population"
        shutil.copytree(SOURCE, stale_dir)
        manifest_path = stale_dir / "population.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["input_sha256"]["candidate_pool"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        optimize("reject_stale_population", population=stale_dir, expect_ok=False)

        stale_pool = ART5 / "stale_pool.json"
        pool_payload = json.loads(POOL.read_text(encoding="utf-8"))
        pool_payload["candidates"][0]["score"] += 1
        stale_pool.write_text(json.dumps(pool_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        optimize("reject_stale_pool", pool=stale_pool, expect_ok=False)
        print("PASS rejection checks: bad weights, oversized search population, stale provenance/pool")

        summary = {
            "schema": 1,
            "status": "pass",
            "mode": "low-cost-prescreen-not-winrate",
            "source_phase4_decks": 100,
            "search_population": 48,
            "generations": 4,
            "actual_engine_duels": 0,
            "win_rate_evaluated": False,
            "byte_identical_repeat": True,
            "seed_sensitivity": True,
            "best_score_ppm": a["decks"][0]["metrics"]["score_ppm"],
        }
        (ART5 / "suite.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print("PHASE5-A SUITE PASS: 48-deck GA prescreen, deterministic repeat, seed sensitivity, constraints, C++ validation; 0 duels")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        (ART5 / "suite_error.txt").write_text(str(error) + "\n", encoding="utf-8")
        print(f"PHASE5-A SUITE FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
