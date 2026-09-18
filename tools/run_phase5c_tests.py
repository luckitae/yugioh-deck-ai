#!/usr/bin/env python3
"""Phase 5-C 실제 고정 DB/CardScripts/OCGCore 통합 검사.

상대는 CI에서 고정 DB로 만드는 서로 다른 일반 몬스터 test-only fixture다. 따라서 이 suite는
실제 승률 Fitness 연결을 검증하지만, 상대 Pool의 경쟁력이나 최종 메타 성능을 주장하지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/phase5c"
DB = ROOT / "data/vendor/BabelCDB/cards.cdb"
SCRIPTS = ROOT / "data/vendor/CardScripts"
RUNNER = ROOT / "phase5_duel"
OPTIMIZER = ROOT / "tools/phase5c_optimize.py"
VALIDATOR = ROOT / "phase4_validate"
SEARCH = ROOT / "artifacts/phase5/search_a"
POOL = ROOT / "artifacts/phase4/single_pool.json"
PACKAGES = ROOT / "artifacts/phase4/population_a/packages.json"
RULES = ROOT / "data/rules/phase4-test-no-banlist.json"


def run(name: str, command: list[str], expect_ok: bool = True, timeout: int = 1200) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    (ART / f"{name}.log").write_text(result.stdout, encoding="utf-8")
    if (result.returncode == 0) != expect_ok:
        raise RuntimeError(f"{name}: unexpected exit={result.returncode}\n{result.stdout}")
    return result


def distinct_normal_cards() -> list[tuple[int, int, int, int]]:
    con = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT id,alias,atk,def FROM datas WHERE (ot & 3) != 0 AND type=17 AND atk >= 0 AND def >= 0 ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    seen: set[int] = set()
    out: list[tuple[int, int, int, int]] = []
    for code, alias, atk, defense in rows:
        key = alias or code
        if key in seen:
            continue
        seen.add(key)
        out.append((code, key, atk, defense))
    if len(out) < 120:
        raise RuntimeError("need at least 120 distinct normal-monster alias groups for fixtures")
    return out


def write_ydk(path: Path, cards: list[int], label: str) -> None:
    if len(cards) != 40 or len(set(cards)) != 40:
        raise RuntimeError("opponent fixture must contain 40 distinct IDs")
    path.write_text(
        f"#created by yugioh-deck-ai phase5-c {label} test-only fixture\n#main\n" +
        "\n".join(map(str, cards)) + "\n#extra\n!side\n",
        encoding="utf-8", newline="\n",
    )


def make_opponent_pool() -> Path:
    rows = distinct_normal_cards()
    high = [row[0] for row in sorted(rows, key=lambda r: (-r[2], r[0]))[:40]]
    high_keys = {row[1] for row in rows if row[0] in set(high)}
    low_rows = [row for row in sorted(rows, key=lambda r: (r[2], r[0])) if row[1] not in high_keys]
    low = [row[0] for row in low_rows[:40]]
    used = set(high) | set(low)
    validation = [row[0] for row in sorted(rows, key=lambda r: (-r[3], r[0])) if row[0] not in used][:40]
    if len(low) != 40 or len(validation) != 40 or high == low:
        raise RuntimeError("could not make three distinct opponent fixtures")
    pool_dir = ART / "opponents"
    pool_dir.mkdir(parents=True, exist_ok=True)
    write_ydk(pool_dir / "normal_high_atk.ydk", high, "high-atk")
    write_ydk(pool_dir / "normal_low_atk.ydk", low, "low-atk")
    write_ydk(pool_dir / "normal_high_def.ydk", validation, "validation-high-def")
    manifest = {
        "schema": 1,
        "id": "phase5c-ci-normal-fixtures-v1",
        "kind": "test-only",
        "note": "CI-only normal-monster fixtures; not a competitive or meta opponent snapshot.",
        "decks": [
            {"id": "normal-high-atk", "file": "normal_high_atk.ydk", "splits": ["training"],
             "note": "40 distinct normal monsters selected by high ATK."},
            {"id": "normal-low-atk", "file": "normal_low_atk.ydk", "splits": ["training"],
             "note": "40 distinct normal monsters selected by low ATK, disjoint from high-ATK fixture."},
            {"id": "normal-high-def-validation", "file": "normal_high_def.ydk", "splits": ["validation"],
             "note": "Held-out CI fixture used only to verify split separation."},
        ],
    }
    path = pool_dir / "opponents.json"
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def validate_output(directory: Path) -> dict:
    payload = json.loads((directory / "search.json").read_text(encoding="utf-8"))
    if payload.get("status") != "duel-optimized" or payload.get("fitness_kind") != "real-ocgcore-win-rate-v1":
        raise RuntimeError("wrong Phase 5-C status/fitness kind")
    if payload.get("duel_evaluated") is not True or payload.get("best_win_rate_evaluated") is not True:
        raise RuntimeError("best result is not a completed real-duel evaluation")
    if payload.get("fitness_primary") != "actual_win_rate_ppm" or payload.get("policy") != "first-legal-v1":
        raise RuntimeError("fitness/policy provenance mismatch")
    pool = payload.get("opponent_pool", {})
    if pool.get("kind") != "test-only" or pool.get("split") != "training":
        raise RuntimeError("opponent pool split/kind mismatch")
    if pool.get("opponents") != ["normal-high-atk", "normal-low-atk"]:
        raise RuntimeError("training split did not select exactly the two training opponents")
    if set(pool.get("deck_sha256", {})) != {"normal-high-atk", "normal-low-atk"} or any(
            not isinstance(value, str) or len(value) != 64 for value in pool.get("deck_sha256", {}).values()):
        raise RuntimeError("opponent deck provenance hashes missing")
    if "normal-high-def-validation" in pool.get("opponents", []):
        raise RuntimeError("validation opponent leaked into training fitness")
    rows = payload.get("decks")
    if not isinstance(rows, list) or len(rows) != 3:
        raise RuntimeError("expected 3 final GA individuals")
    scores = [row["metrics"]["score_ppm"] for row in rows]
    if scores != sorted(scores, reverse=True):
        raise RuntimeError("final population not ranked by actual win-rate score")
    if rows[0]["metrics"]["score_ppm"] != rows[0]["metrics"]["win_rate_ppm"]:
        raise RuntimeError("best fitness score is not exact actual win rate")
    if rows[0]["metrics"]["scheduled_duels"] != 4 or rows[0]["metrics"]["failures"] != 0:
        raise RuntimeError("best deck schedule is not 2 opponents x both seats with no failures")
    if set(rows[0]["metrics"]["per_opponent"]) != {"normal-high-atk", "normal-low-atk"}:
        raise RuntimeError("best deck matchup breakdown missing")
    if rows[0]["metrics"]["going_first"]["scheduled_duels"] != 2 or rows[0]["metrics"]["going_second"]["scheduled_duels"] != 2:
        raise RuntimeError("seat breakdown mismatch")
    if payload.get("actual_engine_duels", 0) < 12 or payload.get("unique_evaluated_decks", 0) < 3:
        raise RuntimeError("too few actual engine evaluations")
    if payload.get("complete_final_decks", 0) < 1:
        raise RuntimeError("no completely evaluated final deck")
    history = payload.get("history")
    if not isinstance(history, list) or len(history) != 2 or history[1]["best_score_ppm"] < history[0]["best_score_ppm"]:
        raise RuntimeError("one-generation real-fitness GA/elitism history mismatch")
    if sum(payload.get("operation_counts", {}).values()) < 2:
        raise RuntimeError("real-fitness GA did not accept mutation children")

    # Best evaluation artifact must contain only the requested training schedule and finished OCGCore results.
    eval_rel = Path(rows[0]["metrics"]["evaluation_file"])
    if eval_rel.is_absolute() or ".." in eval_rel.parts:
        raise RuntimeError("unsafe evaluation artifact path")
    evaluation = json.loads((directory / eval_rel).read_text(encoding="utf-8"))
    cases = evaluation.get("cases")
    if not isinstance(cases, list) or len(cases) != 4:
        raise RuntimeError("best evaluation case count mismatch")
    if any(case.get("status") != "finished" for case in cases):
        raise RuntimeError("best evaluation contains unfinished duel")
    if {case["opponent_id"] for case in cases} != {"normal-high-atk", "normal-low-atk"}:
        raise RuntimeError("held-out opponent leaked into best evaluation")
    if {case["seat"] for case in cases} != {0, 1} or {case["seed"] for case in cases} != {1}:
        raise RuntimeError("best evaluation seed/seat schedule mismatch")

    source = json.loads((SEARCH / "search.json").read_text(encoding="utf-8"))
    required = source["required"]["main"]
    command = [str(VALIDATOR), "--db", str(DB)]
    for code, count in sorted(required.items(), key=lambda kv: int(kv[0])):
        command += ["--required-main", f"{code}={count}"]
    for row in rows:
        relative = Path(row["file"])
        if relative.is_absolute() or ".." in relative.parts or not (directory / relative).is_file():
            raise RuntimeError("bad final YDK path")
        command += ["--deck", str(directory / relative)]
    run("final_cpp_validation", command, timeout=180)
    print(f"PASS phase5c_output: best_win_rate_ppm={rows[0]['metrics']['win_rate_ppm']} actual_duels={payload['actual_engine_duels']} complete_final={payload['complete_final_decks']}/3")
    return payload


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    try:
        prerequisites = [DB, RUNNER, OPTIMIZER, VALIDATOR, SEARCH / "search.json", POOL, PACKAGES, RULES]
        if not all(path.is_file() for path in prerequisites) or not SCRIPTS.is_dir():
            raise RuntimeError("Phase 2/4/5-A/5-B prerequisites missing")
        manifest = make_opponent_pool()
        output = ART / "search_real"
        command = [sys.executable, str(OPTIMIZER), "--db", str(DB), "--scripts", str(SCRIPTS),
                   "--runner", str(RUNNER), "--search", str(SEARCH), "--pool", str(POOL),
                   "--packages", str(PACKAGES), "--rules", str(RULES), "--opponents", str(manifest),
                   "--split", "training", "--output", str(output), "--population-size", "3",
                   "--generations", "1", "--elite", "1", "--tournament", "2",
                   "--mutation-attempts", "200", "--search-seed", "17", "--duel-seeds", "1",
                   "--max-calls", "200000", "--duel-timeout", "90"]
        run("optimize", command, timeout=1800)
        result = validate_output(output)

        suite = {
            "schema": 1,
            "status": "pass",
            "fitness_kind": "real-ocgcore-win-rate-v1",
            "policy": "first-legal-v1",
            "opponent_kind": "test-only",
            "training_opponents": 2,
            "held_out_validation_opponents": 1,
            "duel_seeds": [1],
            "candidate_seats": [0, 1],
            "search_population": 3,
            "generations": 1,
            "actual_engine_duels": result["actual_engine_duels"],
            "best_win_rate_ppm": result["decks"][0]["metrics"]["win_rate_ppm"],
            "best_schedule_complete": True,
            "failures_are_never_wins": True,
            "competitive_opponent_pool_verified": False,
            "strong_policy_verified": False,
        }
        (ART / "suite.json").write_text(json.dumps(suite, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print("PHASE5-C SUITE PASS: actual OCGCore win-rate fitness drives 3-deck GA over 2 test-only training opponents x 1 seed x both seats; best schedule complete")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        (ART / "suite_error.txt").write_text(str(error) + "\n", encoding="utf-8")
        print(f"PHASE5-C SUITE FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
