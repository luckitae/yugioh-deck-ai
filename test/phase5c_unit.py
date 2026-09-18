#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import stat
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from search.duel_fitness import (DuelEvaluator, DuelFitnessError, DuelSchedule,
                                 Opponent, aggregate_cases, load_opponent_pool, parse_seeds)

checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    if not condition:
        raise AssertionError(message)
    checks += 1


def expect_error(fn, message: str) -> None:
    try:
        fn()
        check(False, message)
    except DuelFitnessError:
        check(True, message)


def ydk(path: Path, start: int = 1) -> None:
    cards = list(range(start, start + 40))
    path.write_text("#main\n" + "\n".join(map(str, cards)) + "\n#extra\n!side\n", encoding="utf-8")


def fake_runner(path: Path, fail: bool = False) -> None:
    body = f'''#!/usr/bin/env python3
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser(add_help=False)
for name in ("--db","--scripts","--deck0","--deck1","--seed","--policy","--max-calls","--result","--trace"):
    p.add_argument(name)
a,unknown=p.parse_known_args()
result=Path(a.result); trace=Path(a.trace)
result.parent.mkdir(parents=True, exist_ok=True)
trace.parent.mkdir(parents=True, exist_ok=True)
if {str(fail)}:
    payload={{"schema":1,"runner":"fake","policy":"first-legal-v1","first_player":0,"seed":int(a.seed),"status":"unsupported_selection","error":"fixture failure","winner":None,"engine_errors":0}}
    result.write_text(json.dumps(payload), encoding="utf-8")
    raise SystemExit(1)
payload={{"schema":1,"runner":"fake","policy":"first-legal-v1","first_player":0,"seed":int(a.seed),"status":"finished","error":"","winner":0,"reason":1,"turns":7,"selections":12,"engine_errors":0}}
result.write_text(json.dumps(payload), encoding="utf-8")
trace.write_text('{{"kind":"win"}}\\n', encoding="utf-8")
print("FAKE PASS")
'''
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def main() -> int:
    check(parse_seeds("1,42") == (1, 42), "seed parse")
    check(parse_seeds("0") == (0,), "seed zero")
    expect_error(lambda: parse_seeds(""), "empty seeds rejected")
    expect_error(lambda: parse_seeds("1,1"), "duplicate seeds rejected")
    expect_error(lambda: parse_seeds("-1"), "negative seed rejected")
    expect_error(lambda: DuelSchedule((1,), 0, 90).validate(), "zero max_calls rejected")
    expect_error(lambda: DuelSchedule((1,), 10, 0).validate(), "zero timeout rejected")

    cases = [
        {"opponent_id": "a", "seat": 0, "status": "finished", "outcome": "win", "turns": 5},
        {"opponent_id": "a", "seat": 1, "status": "finished", "outcome": "loss", "turns": 6},
        {"opponent_id": "b", "seat": 0, "status": "finished", "outcome": "draw", "turns": 7},
        {"opponent_id": "b", "seat": 1, "status": "finished", "outcome": "win", "turns": 8},
    ]
    metrics = aggregate_cases(cases)
    check(metrics["score_ppm"] == 500_000, "actual win rate is score")
    check(metrics["wins"] == 2 and metrics["draws"] == 1 and metrics["losses"] == 1, "WDL count")
    check(metrics["win_rate_evaluated"] is True and metrics["failures"] == 0, "complete schedule")
    check(metrics["going_first"]["win_rate_ppm"] == 500_000, "first split")
    check(metrics["going_second"]["win_rate_ppm"] == 500_000, "second split")
    check(metrics["per_opponent"]["a"]["win_rate_ppm"] == 500_000, "opponent a rate")
    check(metrics["per_opponent"]["b"]["win_rate_ppm"] == 500_000, "opponent b rate")
    check(metrics["worst_opponent_win_rate_ppm"] == 500_000, "worst matchup")
    check(metrics["mean_turns_milli"] == 6500, "mean turns")

    failed = list(cases)
    failed[-1] = {"opponent_id": "b", "seat": 1, "status": "timeout", "outcome": None, "turns": None}
    bad = aggregate_cases(failed)
    check(bad["failures"] == 1 and bad["win_rate_evaluated"] is False, "failure marks incomplete")
    check(bad["score_ppm"] == -1, "failure can never become a win fitness")
    check(bad["win_rate_ppm"] is None, "incomplete win rate not published")
    expect_error(lambda: aggregate_cases([]), "empty aggregate rejected")

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        ydk(root / "train.ydk", 1)
        ydk(root / "valid.ydk", 101)
        manifest = root / "opponents.json"
        payload = {
            "schema": 1, "id": "unit-pool-v1", "kind": "test-only", "note": "unit fixture",
            "decks": [
                {"id": "train", "file": "train.ydk", "splits": ["training"], "note": "train"},
                {"id": "valid", "file": "valid.ydk", "splits": ["validation", "final"], "note": "valid"},
            ],
        }
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        meta, training = load_opponent_pool(manifest, "training")
        check(meta["id"] == "unit-pool-v1", "manifest id")
        check([row.id for row in training] == ["train"], "training split filter")
        _, validation = load_opponent_pool(manifest, "validation")
        check([row.id for row in validation] == ["valid"], "validation split filter")
        _, final = load_opponent_pool(manifest, "final")
        check([row.id for row in final] == ["valid"], "final split filter")

        invalid = dict(payload)
        invalid["decks"] = [dict(payload["decks"][0], file="../escape.ydk")]
        bad_manifest = root / "bad.json"
        bad_manifest.write_text(json.dumps(invalid), encoding="utf-8")
        expect_error(lambda: load_opponent_pool(bad_manifest, "training"), "path traversal rejected")
        expect_error(lambda: load_opponent_pool(manifest, "unknown"), "unknown split rejected")

        db = root / "dummy.cdb"; db.write_bytes(b"dummy")
        scripts = root / "scripts"; scripts.mkdir()
        runner = root / "fake_runner.py"; fake_runner(runner)
        work = root / "work"
        schedule = DuelSchedule((1,), 100, 10)
        required = {"main": {1: 2}, "extra": {}}
        evaluator = DuelEvaluator(runner, db, scripts, training, schedule, required, work)
        deck = {"main": list(range(1, 41)), "extra": [], "side": []}
        result = evaluator(deck)
        check(result["scheduled_duels"] == 2 and result["finished_duels"] == 2, "runner schedule")
        check(result["wins"] == 1 and result["losses"] == 1, "seat-aware outcome")
        check(result["score_ppm"] == 500_000 and result["win_rate_evaluated"] is True, "runner win fitness")
        check(evaluator.runner_invocations == 2, "two runner invocations")
        again = evaluator(deck)
        check(again == result and evaluator.runner_invocations == 2, "same deck cached")
        check((work / result["evaluation_file"]).is_file(), "evaluation artifact written")

        fail_runner = root / "fail_runner.py"; fake_runner(fail_runner, True)
        fail_eval = DuelEvaluator(fail_runner, db, scripts, training, schedule, required, root / "failwork")
        failure = fail_eval(deck)
        check(failure["failures"] == 2, "runner failures counted")
        check(failure["score_ppm"] == -1 and failure["win_rate_evaluated"] is False,
              "runner failure disqualified from win-rate fitness")

    print(f"PHASE5-C UNIT PASS: {checks} checks (fake runner; no OCGCore duels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
