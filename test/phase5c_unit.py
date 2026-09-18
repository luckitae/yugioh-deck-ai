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


def fake_runner(path: Path, mode: str = "success") -> None:
    if mode not in {"success", "fail", "poison_finished", "mismatch_id", "truncated_trace", "zero_activity",
                     "missing_result", "timeout", "mutate_input"}:
        raise ValueError("unknown fake runner mode")
    body = '''#!/usr/bin/env python3
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser(add_help=False)
for name in ("--db","--scripts","--deck0","--deck1","--seed","--policy","--max-calls","--run-id","--attempt-id","--result","--trace"):
    p.add_argument(name)
a,unknown=p.parse_known_args()
result=Path(a.result); trace=Path(a.trace)
result.parent.mkdir(parents=True, exist_ok=True)
trace.parent.mkdir(parents=True, exist_ok=True)
mode=__MODE__
def finished_payload():
    return {"schema":2,"result_type":"duel","runner":"phase5b-duel-runner-v2","engine_api":"11.0",
            "run_id":a.run_id,"attempt_id":a.attempt_id,"completed":True,"policy":"first-legal-v1",
            "first_player":0,"seed":int(a.seed),"status":"finished","error":"","winner":0,"reason":1,
            "process_calls":20,"turns":7,"selections":12,"trace_events":3,"engine_errors":0,
            "deck_files":[a.deck0,a.deck1],"trace_file":a.trace}
def write_trace(truncated=False):
    text='{"seq":1,"kind":"turn","player":0}\\n{"seq":2,"kind":"selection"}\\n{"seq":3,"kind":"win","player":0,"value":1}'
    trace.write_text(text if truncated else text+'\\n', encoding="utf-8")
if mode=="timeout":
    import time; time.sleep(5)
if mode=="missing_result":
    print("FAKE NO RESULT"); raise SystemExit(0)
if mode=="fail":
    payload={"schema":2,"result_type":"duel","runner":"phase5b-duel-runner-v2","engine_api":"11.0",
             "run_id":a.run_id,"attempt_id":a.attempt_id,"completed":False,"policy":"first-legal-v1",
             "first_player":0,"seed":int(a.seed),"status":"unsupported_selection","error":"fixture failure",
             "winner":None,"reason":None,"engine_errors":0}
    result.write_text(json.dumps(payload), encoding="utf-8")
    raise SystemExit(1)
payload=finished_payload()
if mode=="mismatch_id":
    payload["attempt_id"]="wrong-attempt"
if mode=="zero_activity":
    payload["process_calls"]=1; payload["turns"]=0; payload["selections"]=0; payload["trace_events"]=1
    trace.write_text('{"seq":1,"kind":"win","player":0,"value":1}\\n', encoding="utf-8")
else:
    write_trace(mode=="truncated_trace")
if mode=="mutate_input":
    with open(a.deck0, "ab") as stream: stream.write(b"\\n")
result.write_text(json.dumps(payload), encoding="utf-8")
if mode=="poison_finished":
    raise SystemExit(1)
print("FAKE PASS")
'''.replace("__MODE__", repr(mode))
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

        fail_runner = root / "fail_runner.py"; fake_runner(fail_runner, "fail")
        fail_eval = DuelEvaluator(fail_runner, db, scripts, training, schedule, required, root / "failwork")
        failure = fail_eval(deck)
        check(failure["failures"] == 2, "runner failures counted")
        check(failure["score_ppm"] == -1 and failure["win_rate_evaluated"] is False,
              "runner failure disqualified from win-rate fitness")
        fail_record = json.loads((root / "failwork" / failure["evaluation_file"]).read_text(encoding="utf-8"))
        check(all(case["status"] == "unsupported" and case["outcome"] is None for case in fail_record["cases"]),
              "unsupported runner failure normalized with null outcome")

        # R0-2 regression: nonzero exit must dominate a forged/stale-looking finished JSON.
        poison_runner = root / "poison_runner.py"; fake_runner(poison_runner, "poison_finished")
        poison_work = root / "poisonwork"
        poison_eval = DuelEvaluator(poison_runner, db, scripts, training, schedule, required, poison_work)
        poison = poison_eval(deck)
        check(poison["failures"] == 2 and poison["score_ppm"] == -1, "nonzero finished JSON rejected")
        poison_record = json.loads((poison_work / poison["evaluation_file"]).read_text(encoding="utf-8"))
        check(all(case["status"] == "runner_error" and case["runner_status"] == "finished" for case in poison_record["cases"]),
              "contradictory finished payload normalized to runner_error")
        check(all(case["outcome"] is None and case["winner"] is None for case in poison_record["cases"]),
              "failed process cannot retain winner/outcome")

        missing_runner = root / "missing_runner.py"; fake_runner(missing_runner, "missing_result")
        missing_work = root / "missingwork"
        missing_eval = DuelEvaluator(missing_runner, db, scripts, training, schedule, required, missing_work)
        missing = missing_eval(deck)
        missing_record = json.loads((missing_work / missing["evaluation_file"]).read_text(encoding="utf-8"))
        check(all(case["status"] == "missing_result" and case["outcome"] is None for case in missing_record["cases"]),
              "success exit without result rejected")

        timeout_runner = root / "timeout_runner.py"; fake_runner(timeout_runner, "timeout")
        timeout_work = root / "timeoutwork"
        timeout_eval = DuelEvaluator(timeout_runner, db, scripts, training, DuelSchedule((1,), 100, 1), required, timeout_work)
        timeout_result = timeout_eval(deck)
        timeout_record = json.loads((timeout_work / timeout_result["evaluation_file"]).read_text(encoding="utf-8"))
        check(all(case["status"] == "timeout" and case["outcome"] is None for case in timeout_record["cases"]),
              "timeout normalized with null outcome")

        mismatch_runner = root / "mismatch_runner.py"; fake_runner(mismatch_runner, "mismatch_id")
        mismatch_work = root / "mismatchwork"
        mismatch_eval = DuelEvaluator(mismatch_runner, db, scripts, training, schedule, required, mismatch_work)
        mismatch = mismatch_eval(deck)
        mismatch_record = json.loads((mismatch_work / mismatch["evaluation_file"]).read_text(encoding="utf-8"))
        check(all(case["status"] == "provenance_error" for case in mismatch_record["cases"]),
              "run/attempt mismatch rejected")

        truncated_runner = root / "truncated_runner.py"; fake_runner(truncated_runner, "truncated_trace")
        truncated_work = root / "truncatedwork"
        truncated_eval = DuelEvaluator(truncated_runner, db, scripts, training, schedule, required, truncated_work)
        truncated = truncated_eval(deck)
        truncated_record = json.loads((truncated_work / truncated["evaluation_file"]).read_text(encoding="utf-8"))
        check(all(case["status"] == "trace_error" for case in truncated_record["cases"]),
              "truncated trace rejected")
        check(truncated["win_rate_evaluated"] is False, "trace failure blocks evaluated win rate")

        zero_runner = root / "zero_runner.py"; fake_runner(zero_runner, "zero_activity")
        zero_eval = DuelEvaluator(zero_runner, db, scripts, training, schedule, required, root / "zerowork")
        zero = zero_eval(deck)
        check(zero["finished_duels"] == 2 and zero["win_rate_evaluated"] is True,
              "legal zero-turn/zero-selection completion accepted")

        mutate_runner = root / "mutate_runner.py"; fake_runner(mutate_runner, "mutate_input")
        mutate_work = root / "mutatework"
        mutate_eval = DuelEvaluator(mutate_runner, db, scripts, training, schedule, required, mutate_work)
        mutate = mutate_eval(deck)
        mutate_record = json.loads((mutate_work / mutate["evaluation_file"]).read_text(encoding="utf-8"))
        check(all(case["status"] == "provenance_error" and case["outcome"] is None for case in mutate_record["cases"]),
              "input deck mutation during runner execution rejected")

    print(f"PHASE5-C UNIT PASS: {checks} checks (fake runner; no OCGCore duels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
