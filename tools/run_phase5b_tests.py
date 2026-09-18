#!/usr/bin/env python3
"""Phase 5-B: Phase 5-A 상위 덱을 실제 OCGCore에서 deterministic first-legal bot으로 듀얼한다.

이 suite의 상대는 실전 메타 덱이 아니라 DB에서 고른 서로 다른 일반 몬스터 40장 fixture다.
따라서 실제 듀얼 실행 여부를 검증하지만 최종 최적화 승률이나 메타 성능을 주장하지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/phase5b"
DB = ROOT / "data/vendor/BabelCDB/cards.cdb"
SCRIPTS = ROOT / "data/vendor/CardScripts"
SEARCH = ROOT / "artifacts/phase5/search_a"
RUNNER = ROOT / "phase5_duel"


def run(name: str, command: list[str], expect_ok: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=90)
    (ART / f"{name}.log").write_text(result.stdout, encoding="utf-8")
    if (result.returncode == 0) != expect_ok:
        raise RuntimeError(f"{name}: unexpected exit={result.returncode}\n{result.stdout}")
    return result


def make_normal_fixture(path: Path) -> None:
    con = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT id,alias FROM datas WHERE (ot & 3) != 0 AND type=17 ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    chosen: list[int] = []
    keys: set[int] = set()
    for code, alias in rows:
        key = alias or code
        if key in keys:
            continue
        keys.add(key)
        chosen.append(code)
        if len(chosen) == 40:
            break
    if len(chosen) != 40:
        raise RuntimeError("could not build 40-card normal-monster fixture")
    text = "#created by yugioh-deck-ai phase5-b fixture\n#main\n" + "\n".join(map(str, chosen)) + "\n#extra\n!side\n"
    path.write_text(text, encoding="utf-8")


def duel(name: str, deck0: Path, deck1: Path, seed: int, required: dict[str, int], required_player: int) -> dict:
    result_path = ART / f"{name}.json"
    trace_path = ART / f"{name}.jsonl"
    run_id = "phase5b-ci"
    attempt_id = name.replace("_", "-")
    command = [str(RUNNER), "--db", str(DB), "--scripts", str(SCRIPTS),
               "--deck0", str(deck0), "--deck1", str(deck1), "--seed", str(seed),
               "--policy", "first-legal-v1", "--max-calls", "200000",
               "--run-id", run_id, "--attempt-id", attempt_id,
               "--result", str(result_path), "--trace", str(trace_path)]
    for code, count in sorted(required.items(), key=lambda kv: int(kv[0])):
        command += [f"--required-main{required_player}", f"{code}={count}"]
    run(name, command)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if (payload.get("schema") != 2 or payload.get("result_type") != "duel" or
            payload.get("runner") != "phase5b-duel-runner-v2" or payload.get("completed") is not True or
            payload.get("run_id") != run_id or payload.get("attempt_id") != attempt_id):
        raise RuntimeError(f"{name}: R0 runner result contract mismatch")
    if payload.get("status") != "finished" or payload.get("winner") not in (0, 1, 2):
        raise RuntimeError(f"{name}: not a finished duel")
    if payload.get("selections", 0) <= 0 or payload.get("turns", 0) <= 0:
        raise RuntimeError(f"{name}: duel did not exercise bot selections/turns")
    if payload.get("engine_errors") != 0:
        raise RuntimeError(f"{name}: engine script errors were reported")
    if not trace_path.is_file() or trace_path.stat().st_size == 0:
        raise RuntimeError(f"{name}: trace missing")
    print(f"PASS {name}: winner={payload['winner']} turns={payload['turns']} selections={payload['selections']}")
    return payload


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    try:
        search_path = SEARCH / "search.json"
        if not all([DB.is_file(), SCRIPTS.is_dir(), RUNNER.is_file(), search_path.is_file()]):
            raise RuntimeError("Phase 2/5-A prerequisites or phase5_duel missing")
        search = json.loads(search_path.read_text(encoding="utf-8"))
        if search.get("status") != "prescreened" or search.get("duel_evaluated") is not False:
            raise RuntimeError("unexpected Phase 5-A provenance")
        required = search.get("required", {}).get("main")
        if not isinstance(required, dict) or not required:
            raise RuntimeError("Phase 5-A required Main block missing")
        decks = search.get("decks")
        if not isinstance(decks, list) or len(decks) < 2:
            raise RuntimeError("need at least two Phase 5-A decks")
        normal = ART / "normal40.ydk"
        make_normal_fixture(normal)

        results: list[dict] = []
        cases: list[dict] = []
        seeds = (1, 42)
        for rank, row in enumerate(decks[:2], start=1):
            rel = Path(row["file"])
            if rel.is_absolute() or ".." in rel.parts:
                raise RuntimeError("unsafe Phase 5-A deck path")
            candidate = SEARCH / rel
            if not candidate.is_file():
                raise RuntimeError(f"missing Phase 5-A deck: {candidate}")
            for seed in seeds:
                first_name = f"rank{rank}_seed{seed}_candidate_first"
                a = duel(first_name, candidate, normal, seed, required, 0)
                results.append(a); cases.append({"rank": rank, "seed": seed, "seat": 0, "result": first_name})
                second_name = f"rank{rank}_seed{seed}_candidate_second"
                b = duel(second_name, normal, candidate, seed, required, 1)
                results.append(b); cases.append({"rank": rank, "seed": seed, "seat": 1, "result": second_name})

        finished = len(results)
        candidate_wins = 0
        draws = 0
        prompt_types: set[str] = set()
        for case, result in zip(cases, results):
            winner = result["winner"]
            if winner == 2:
                draws += 1
            elif winner == case["seat"]:
                candidate_wins += 1
            prompt_types.update(result.get("prompts", {}).keys())
        if finished != 8:
            raise RuntimeError("expected exactly 8 finished engine duels")
        if len(prompt_types) < 2:
            raise RuntimeError("duels exercised too few selection prompt types")
        summary = {
            "schema": 1,
            "status": "pass",
            "runner": "phase5b-duel-runner-v2",
            "policy": "first-legal-v1",
            "actual_engine_duels": finished,
            "candidate_decks": 2,
            "seeds": list(seeds),
            "candidate_seats": [0, 1],
            "candidate_wins": candidate_wins,
            "draws": draws,
            "fixture_win_rate_ppm": candidate_wins * 1_000_000 // finished,
            "opponent_kind": "40-distinct-normal-monster-test-fixture",
            "final_fitness_win_rate": False,
            "prompt_types": sorted(prompt_types),
            "cases": cases,
        }
        (ART / "suite.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print("PHASE5-B SUITE PASS: 8 real OCGCore duels, 2 prescreened decks x 2 seeds x both seats, traces recorded")
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        (ART / "suite_error.txt").write_text(str(error) + "\n", encoding="utf-8")
        print(f"PHASE5-B SUITE FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
