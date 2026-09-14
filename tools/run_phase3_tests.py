#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
DB = ROOT / "data/vendor/BabelCDB/cards.cdb"
BINARY = ROOT / "phase3_analyze"
ALLOWED_FEATURES = {
    "SEARCH", "DRAW", "SPECIAL_SUMMON", "NORMAL_SUMMON", "NEGATE", "DESTROY",
    "BANISH", "RETURN", "SEND_TO_GY", "RECOVER", "MATERIAL", "TOKEN",
    "PROTECTION", "DISCARD", "TRIGGER", "TARGET",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name: str, required: list[int], extra: list[str] | None = None, expect_ok: bool = True) -> tuple[subprocess.CompletedProcess[str], Path]:
    output = ARTIFACTS / f"phase3_{name}.json"
    command = [str(BINARY), "--db", str(DB)]
    for code in required:
        command += ["--required", str(code)]
    command += ["--output", str(output)]
    if extra:
        command += extra
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    (ARTIFACTS / f"phase3_{name}.log").write_text(result.stdout, encoding="utf-8")
    if expect_ok and result.returncode != 0:
        raise RuntimeError(f"{name} failed:\n{result.stdout}")
    if not expect_ok and result.returncode == 0:
        raise RuntimeError(f"{name} unexpectedly succeeded")
    return result, output


def validate_output(path: Path, required: list[int]) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != 1 or payload.get("analysis_profile") != "phase3-text-metadata-v1":
        raise RuntimeError("unexpected Phase 3 schema/profile")
    if payload.get("required") != required:
        raise RuntimeError("required list was not preserved")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) <= len(required):
        raise RuntimeError("candidate pool did not expand beyond required cards")
    codes = [item["code"] for item in candidates]
    if len(codes) != len(set(codes)):
        raise RuntimeError("duplicate candidate code")
    for index, code in enumerate(required):
        item = candidates[index]
        if item["code"] != code or item["pool"] != "REQUIRED":
            raise RuntimeError("required cards are not retained at the head of the pool")
    pools = {item["pool"] for item in candidates}
    if "ENGINE" not in pools:
        raise RuntimeError("no engine candidates")
    if "GENERIC" not in pools:
        raise RuntimeError("no generic candidates")
    if not any(any(rel["strength"] == "STRONG" for rel in item["relations"])
               for item in candidates if item["pool"] == "ENGINE"):
        raise RuntimeError("no strong relationship was found")
    if not any(any(rel["strength"] == "MEDIUM" for rel in item["relations"])
               for item in candidates if item["pool"] == "ENGINE"):
        raise RuntimeError("no medium relationship was found")
    for item in candidates:
        if not set(item["features"]).issubset(ALLOWED_FEATURES):
            raise RuntimeError("unknown feature emitted")
        if not item["relations"]:
            raise RuntimeError("candidate without inclusion reason")
    if len(candidates) > payload["config"]["total_limit"]:
        raise RuntimeError("total candidate limit exceeded")
    return payload


def main() -> int:
    ARTIFACTS.mkdir(exist_ok=True)
    if not DB.is_file() or not BINARY.is_file():
        print("PHASE3 SUITE FAIL: required DB/binary missing", file=sys.stderr)
        return 1
    try:
        # 대표적으로 직접 이름 참조가 많은 카드. 실제 DB에 없으면 조용히 대체하지 않고 실패한다.
        single_required = [89631139]  # Blue-Eyes White Dragon
        _, first = run("blue_eyes_a", single_required)
        first_payload = validate_output(first, single_required)
        first_hash = sha(first)
        _, second = run("blue_eyes_b", single_required)
        validate_output(second, single_required)
        if sha(second) != first_hash:
            raise RuntimeError("same inputs did not produce byte-identical candidate output")

        multiple_required = [89631139, 46986414]  # + Dark Magician
        _, multi = run("multi_required", multiple_required, ["--engine-limit", "60", "--generic-limit", "30", "--total-limit", "90"])
        multi_payload = validate_output(multi, multiple_required)

        _, limited = run("limited", single_required, ["--engine-limit", "5", "--generic-limit", "3", "--total-limit", "9"])
        limited_payload = validate_output(limited, single_required)
        if len(limited_payload["candidates"]) > 9:
            raise RuntimeError("explicit small total limit ignored")

        run("missing_required", [4294967295], expect_ok=False)
        summary = {
            "schema": 1,
            "status": "pass",
            "single_required": single_required,
            "single_candidates": len(first_payload["candidates"]),
            "single_sha256": first_hash,
            "multi_required": multiple_required,
            "multi_candidates": len(multi_payload["candidates"]),
            "deterministic_repeat": True,
            "negative_missing_required": "rejected",
        }
        (ARTIFACTS / "phase3_suite.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print("PHASE3 SUITE PASS: deterministic candidate pools, explanations, limits, and rejection checks")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        (ARTIFACTS / "phase3_suite_error.txt").write_text(str(error) + "\n", encoding="utf-8")
        print(f"PHASE3 SUITE FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
