#!/usr/bin/env python3
"""실제 pinned DB/Lua와 네이티브 OCGCore를 사용하는 Actions 통합 검사."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts"
DB = ROOT / "data/vendor/BabelCDB/cards.cdb"
SCRIPTS = ROOT / "data/vendor/CardScripts"
BINARY = ROOT / "phase2_smoke"
HINOTAMA = 46130346


def write_deck(path: Path, main: list[int], extra: tuple[int, ...] = (), side: tuple[int, ...] = ()) -> Path:
    text = "#created by Phase 2 integration fixtures; no tournament banlist\n#main\n"
    text += "".join(f"{code}\n" for code in main)
    text += "#extra\n" + "".join(f"{code}\n" for code in extra)
    text += "!side\n" + "".join(f"{code}\n" for code in side)
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    ARTIFACT.mkdir(exist_ok=True)
    decks_dir = ARTIFACT / "decks"
    decks_dir.mkdir(exist_ok=True)
    summary: dict = {"schema": 1, "status": "failed", "tests": [], "error": None}
    try:
        if not BINARY.is_file():
            raise RuntimeError("Build phase2_smoke before running this suite")
        if not (ARTIFACT / "data_manifest.json").is_file():
            raise RuntimeError("Run fetch_phase2_data.py before running this suite")
        con = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT d.id,t.name FROM datas d JOIN texts t ON t.id=d.id "
                "WHERE d.type=17 AND d.alias=0 AND (d.ot & 3) != 0 ORDER BY d.id LIMIT 30"
            ).fetchall()
            # 비효과 융합 몬스터: Extra 투입 검사용이며 소환은 하지 않는다.
            fusion_rows = con.execute(
                "SELECT d.id,t.name FROM datas d JOIN texts t ON t.id=d.id "
                "WHERE d.type=65 AND d.alias=0 AND (d.ot & 3) != 0 ORDER BY d.id"
            ).fetchall()
            names = {int(code): name for code, name in rows}
            found = con.execute("SELECT name FROM texts WHERE id=?", (HINOTAMA,)).fetchone()
            if found is None:
                raise RuntimeError("Hinotama is missing from actual database")
            names[HINOTAMA] = found[0]
            unknown = 4294967295
            while con.execute("SELECT 1 FROM datas WHERE id=?", (unknown,)).fetchone():
                unknown -= 1
        finally:
            con.close()
        if len(rows) < 30:
            raise RuntimeError("Not enough distinct normal monsters for deterministic fixtures")
        extra_code = next((int(code) for code, _ in fusion_rows if (SCRIPTS / f"official/c{code}.lua").is_file()), None)
        if extra_code is None:
            raise RuntimeError("No supported real Fusion card/script for Extra loading test")
        names[extra_code] = next(name for code, name in fusion_rows if int(code) == extra_code)
        pool = [int(code) for code, _ in rows]
        repeated = [code for code in pool for _ in range(3)]
        normal = {n: write_deck(decks_dir / f"normal{n}.ydk", repeated[:n]) for n in range(40, 61)}
        effect = write_deck(decks_dir / "hinotama40.ydk", [HINOTAMA] * 3 + repeated[:37])
        sections = write_deck(decks_dir / "with_extra_side.ydk", repeated[:40], (extra_code,), (pool[-1],))
        fixture_manifest = {
            "selection_rule": "type=17, alias=0, ot&3, ID ascending, at most 3 copies; no banlist",
            "cards": names,
            "ydk_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(decks_dir.glob("*.ydk"))},
        }
        (ARTIFACT / "fixture_manifest.json").write_text(json.dumps(fixture_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def check(name: str, deck: Path, *, seed: int = 1, policy: str = "pass", expected: str = "finished",
                  validate: bool = False, db: Path = DB, scripts: Path = SCRIPTS,
                  required: str | None = None, expected_extra: int = 0, expected_side: int = 0,
                  error_contains: str | None = None) -> None:
            result_path = ARTIFACT / f"{name}.json"
            result_path.unlink(missing_ok=True)  # 이전 실행 결과를 실패한 새 실행에 재사용하지 않는다.
            args = [str(BINARY), "--db", str(db), "--scripts", str(scripts),
                    "--deck0", str(deck), "--deck1", str(deck), "--seed", str(seed),
                    "--policy", policy, "--result", str(result_path)]
            if validate:
                args.append("--validate-only")
            if required:
                args += ["--required-main", required]
            record = {"name": name, "expected": expected, "passed": False, "command": args,
                      "deck_sha256": hashlib.sha256(deck.read_bytes()).hexdigest()}
            summary["tests"].append(record)
            with (ARTIFACT / f"{name}.log").open("w", encoding="utf-8") as log:
                try:
                    proc = subprocess.run(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=120, check=False)
                except subprocess.TimeoutExpired as error:
                    record["error"] = "timeout (not a duel result)"
                    raise RuntimeError(f"{name}: execution timed out") from error
            record["returncode"] = proc.returncode
            if not result_path.is_file():
                raise RuntimeError(f"{name}: no structured result; inspect its log")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            record["actual"] = result.get("status")
            should_pass = expected in ("finished", "validated")
            if (proc.returncode == 0) != should_pass or result.get("status") != expected:
                raise RuntimeError(f"{name}: expected {expected}, got {result.get('status')}; {result.get('error')}")
            if error_contains and error_contains not in result.get("error", ""):
                raise RuntimeError(f"{name}: wrong failure reason: {result.get('error')}")
            if result.get("profile") != "mr5-no-banlist-smoke-v1":
                raise RuntimeError(f"{name}: profile mismatch")
            if expected == "finished":
                if result.get("winner") not in (0, 1, 2) or result.get("engine_errors") != 0 or result.get("scripts_loaded", 0) == 0:
                    raise RuntimeError(f"{name}: invalid finished result")
                if result.get("extra") != [expected_extra] * 2 or result.get("side") != [expected_side] * 2:
                    raise RuntimeError(f"{name}: Extra/Side mismatch")
                if policy == "hinotama-smoke":
                    if min(result.get("activations", 0), result.get("chains_solved", 0), result.get("damage_events", 0)) <= 0:
                        raise RuntimeError(f"{name}: real effect evidence is absent")
                    if result.get("effect_damage") != 500 * result["damage_events"]:
                        raise RuntimeError(f"{name}: effect damage accounting mismatch")
            elif result.get("winner") is not None or result.get("reason") is not None:
                raise RuntimeError(f"{name}: a validation/error was incorrectly counted as a duel result")
            record["passed"] = True
            print(f"PASS {name}: {expected}", flush=True)

        # 전 범위 40..60 검사. 원본 DB 검증과 입력 검증은 듀얼 루프와 분리한다.
        for size in range(40, 61):
            check(f"validate_{size}", normal[size], validate=True, expected="validated")
        check("validate_required", effect, validate=True, expected="validated", required=f"{HINOTAMA}=3")
        for seed in (1, 42):
            check(f"normal40_seed{seed}", normal[40], seed=seed)
            check(f"normal60_seed{seed}", normal[60], seed=seed)
            check(f"extra_side_seed{seed}", sections, seed=seed, expected_extra=1, expected_side=1)
            check(f"hinotama_seed{seed}", effect, seed=seed, policy="hinotama-smoke", required=f"{HINOTAMA}=3")
        # 오류를 승/패로 세지 않는지 실제 실행 파일에서 확인한다.
        invalid39 = write_deck(decks_dir / "invalid39.ydk", repeated[:39])
        invalid61 = write_deck(decks_dir / "invalid61.ydk", repeated[:61])
        copies4 = write_deck(decks_dir / "invalid_copies4.ydk", [pool[0]] * 4 + repeated[3:39])
        missing_card = write_deck(decks_dir / "invalid_unknown.ydk", [unknown] + repeated[:39])
        for name, deck in (("reject39", invalid39), ("reject61", invalid61), ("reject4copies", copies4), ("reject_unknown", missing_card)):
            check(name, deck, validate=True, expected="input_error")
        check("reject_missing_db", normal[40], validate=True, expected="input_error", db=ARTIFACT / "missing.cdb")
        check("reject_missing_required", normal[40], validate=True, expected="input_error", required=f"{HINOTAMA}=1")
        check("reject_unsupported_policy_card", effect, expected="input_error")
        empty_scripts = ARTIFACT / "empty_scripts"
        empty_scripts.mkdir(exist_ok=True)
        check("reject_missing_common_lua", normal[40], scripts=empty_scripts, expected="resource_error", error_contains="constant.lua")
        # 공통 helper만 복사하고 효과 Lua를 생략한다. 비효과 카드의 누락과 구별해야 한다.
        import shutil
        without_effect = ARTIFACT / "scripts_without_effect"
        without_effect.mkdir(exist_ok=True)
        for file in SCRIPTS.glob("*.lua"):
            shutil.copyfile(file, without_effect / file.name)
        (without_effect / "unofficial").mkdir(exist_ok=True)
        shutil.copyfile(SCRIPTS / "unofficial/proc_unofficial.lua", without_effect / "unofficial/proc_unofficial.lua")
        check("reject_missing_effect_lua", effect, scripts=without_effect, policy="hinotama-smoke", expected="resource_error", error_contains="c46130346.lua")
        # 복사한 제3자 helper는 결과 artifact에 넣지 않는다.
        shutil.rmtree(without_effect)
        summary["status"] = "passed"
        summary["duels"] = 8
        print(f"PHASE2 SUITE PASS: {len(summary['tests'])} checks, 8 real-engine duels", flush=True)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        summary["error"] = str(error)
        print(f"PHASE2 SUITE FAIL: {error}", file=sys.stderr)
        return 1
    finally:
        (ARTIFACT / "phase2_suite.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
