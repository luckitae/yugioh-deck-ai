#!/usr/bin/env python3
"""Phase 3 JSON + DB + 명시적 규칙 프로필 -> 재현 가능한 .ydk population."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from pathlib import Path
import platform
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from deck.experiment import PreparedExperiment, load_prepared_experiment
from deck.generator import VERSION, GenerationConfig, generate_population
from deck.packages import build_packages, read_pool
from deck.rules import CardCatalog, DeckError, RuleProfile, SECTIONS, json_text, read_json, sha256, ydk_text


def parse_required(values: list[str]) -> dict[int, int]:
    out = {}
    for value in values:
        pieces = value.split("=")
        if len(pieces) != 2 or any(not t.isascii() or not t.isdecimal() for t in pieces):
            raise DeckError("required format: code=count (example: 89631139=2)")
        code, count = map(int, pieces)
        if not 1 <= code <= 0xFFFFFFFF or not 1 <= count <= 3 or code in out:
            raise DeckError("invalid/repeated required card or count")
        out[code] = count
    return dict(sorted(out.items()))


def parse_sizes(value: str) -> tuple[int, ...]:
    values: list[int] = []
    for item in value.split(","):
        parts = item.split(":")
        if len(parts) not in (1, 2) or any(not t.isascii() or not t.isdecimal() for t in parts):
            raise DeckError("sizes format: 40:60 or 40,50,60")
        low, high = int(parts[0]), int(parts[-1])
        if not 40 <= low <= high <= 60:
            raise DeckError("sizes must be in 40..60")
        values.extend(range(low, high + 1))
    # 중복/역순을 정규화해 같은 의도를 같은 입력으로 기록한다.
    return tuple(sorted(set(values)))


def write_population(output: Path, result: dict, metadata: dict, packages: dict) -> None:
    if output.exists():
        raise DeckError(f"output already exists (will not overwrite): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".phase4-", dir=output.parent))
    try:
        (staging / "decks").mkdir()
        for index, deck in enumerate(result["decks"]):
            relative = f"decks/{index:04d}_{deck['deck_id'][:16]}.ydk"
            (staging / relative).write_text(ydk_text(deck), encoding="utf-8", newline="\n")
            deck["file"] = relative
        manifest = {**metadata, **result, "status": "generated",
                    "tournament_legality_verified": False, "win_rate_evaluated": False,
                    "package_combo_verified": False}
        (staging / "population.json").write_text(json_text(manifest), encoding="utf-8", newline="\n")
        (staging / "packages.json").write_text(json_text({"schema": 1, "packages": [
            package.to_json() for package in packages.values()]}), encoding="utf-8", newline="\n")
        (staging / "SUMMARY.txt").write_text(
            f"Generated: {len(result['decks'])} unique decks\n"
            f"Rules: {metadata['rules']['id']} ({metadata['rules']['kind']})\n"
            "Validation: structure + supplied-profile copy limits only\n"
            "Tournament legality: NOT VERIFIED\nDuel strength/win rate: NOT EVALUATED\n"
            "Package links: HEURISTIC, not verified combos\n", encoding="utf-8")
        # 완성된 디렉터리만 공개한다. 기존 결과는 삭제하지 않는다.
        if output.exists():
            raise DeckError("output appeared while generating; refusing to overwrite")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--required-main", action="append", default=[])
    parser.add_argument("--required-extra", action="append", default=[])
    parser.add_argument("--required-side", action="append", default=[])
    parser.add_argument("--experiment", type=Path, help="prepared R1 experiment directory")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--sizes")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--extra-size", type=int)
    parser.add_argument("--side-size", type=int)
    parser.add_argument("--max-packages", type=int, default=3)
    parser.add_argument("--attempts-per-deck", type=int, default=100)
    parser.add_argument("--packages", type=Path)
    parser.add_argument("--force-package", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise DeckError(f"output already exists (will not overwrite): {args.output}")
        catalog = CardCatalog(args.db)
        rules = RuleProfile(read_json(args.rules), catalog)
        prepared: PreparedExperiment | None = None
        allowed_codes: frozenset[int] | None = None
        experiment = None
        if args.experiment is not None:
            prepared = load_prepared_experiment(args.experiment, catalog, rules, args.db, args.rules)
            allowed_codes = prepared.allowed_codes
            experiment = prepared.spec

        cli_required = {
            "main": parse_required(args.required_main),
            "extra": parse_required(args.required_extra),
            "side": parse_required(args.required_side),
        }
        if experiment is None:
            if cli_required["side"]:
                raise DeckError("--required-side requires --experiment")
            required = {"main": cli_required["main"], "extra": cli_required["extra"]}
            if not any(required.values()):
                raise DeckError("at least one --required-main or --required-extra is required")
        else:
            required = experiment.required_minima()
            if any(cli_required[section] for section in SECTIONS) and cli_required != required:
                raise DeckError("CLI required minima do not match prepared ExperimentSpec")
            if not any(required.values()):
                raise DeckError("ExperimentSpec must contain at least one positive required minimum")

        seen_required: set[int] = set()
        for section in required:
            overlap = seen_required & set(required[section])
            if overlap:
                raise DeckError("same required ID appears in multiple sections")
            seen_required.update(required[section])

        size_text = args.sizes
        if size_text is None:
            size_text = (f"{experiment.main_min}:{experiment.main_max}"
                         if experiment is not None else "40:60")
        side_size = args.side_size
        if side_size is None:
            side_size = experiment.side_min if experiment is not None else 0
        config = GenerationConfig(args.count, parse_sizes(size_text), args.seed, args.extra_size,
                                  side_size, args.max_packages, args.attempts_per_deck)
        config.validate()

        payload = read_json(args.pool)
        candidates, excluded = read_pool(payload, rules, required, allowed_codes)
        supplied = read_json(args.packages) if args.packages else None
        packages = build_packages(candidates, rules, supplied, allowed_codes)
        result = generate_population(candidates, packages, rules, required, config, args.force_package,
                                     allowed_codes, experiment)
        metadata = {"schema": 1, "generator": VERSION, "python_version": platform.python_version(),
                    "analysis_profile": payload["analysis_profile"], "config": asdict(config),
                    "required": {s: {str(code): n for code, n in counts.items()} for s, counts in required.items()},
                    "experiment": None if prepared is None else {
                        "id": prepared.spec.experiment_id,
                        "allowed_set_sha256": prepared.allowed_sha256,
                    },
                    "forced_packages": sorted(set(args.force_package)), "rules": rules.payload,
                    "input_sha256": {"database": sha256(args.db), "candidate_pool": sha256(args.pool),
                                     "rules": sha256(args.rules),
                                     "packages": sha256(args.packages) if args.packages else None,
                                     "experiment_manifest": sha256(args.experiment / "experiment.normalized.json") if args.experiment else None,
                                     "allowed_set": prepared.allowed_sha256 if prepared else None},
                    "source_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in sorted([
                        ROOT / "src/deck/rules.py", ROOT / "src/deck/packages.py",
                        ROOT / "src/deck/generator.py", ROOT / "src/deck/experiment.py",
                        Path(__file__).resolve()])},
                    "eligible_candidates": len(candidates), "excluded_candidates": excluded,
                    "package_count": len(packages)}
        write_population(args.output, result, metadata, packages)
        print(f"PHASE4 GENERATE PASS: decks={len(result['decks'])} sizes={','.join(map(str, config.sizes))} "
              f"rules={rules.payload['id']}")
        print("NOT tournament-certified; NOT win-rate-evaluated")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"PHASE4 GENERATE FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
