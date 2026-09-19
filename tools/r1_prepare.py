#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from deck.experiment import allowed_set_sha256, allowed_set_text, build_allowed_set, load_experiment
from deck.rules import CardCatalog, DeckError, RuleProfile, json_text, read_json, sha256


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize an ExperimentSpec and materialize its shared allowed set.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise DeckError(f"output already exists (will not overwrite): {args.output}")
        catalog = CardCatalog(args.db)
        rules = RuleProfile(read_json(args.rules), catalog)
        spec = load_experiment(args.spec, catalog, rules)
        allowed = build_allowed_set(spec, catalog, rules)
        text = allowed_set_text(allowed)
        digest = allowed_set_sha256(allowed)
        args.output.mkdir(parents=True)
        (args.output / "allowed_ids.txt").write_text(text, encoding="ascii", newline="\n")
        manifest = {
            "schema": 1,
            "experiment_id": spec.experiment_id,
            "normalized_spec": spec.normalized,
            "allowed_set": {"count": len(allowed), "sha256": digest, "file": "allowed_ids.txt"},
            "input_sha256": {
                "spec": sha256(args.spec),
                "database": sha256(args.db),
                "rules": sha256(args.rules),
            },
        }
        (args.output / "experiment.normalized.json").write_text(
            json_text(manifest), encoding="utf-8", newline="\n"
        )
        print(
            f"R1 PREPARE PASS: experiment={spec.experiment_id[:16]} "
            f"allowed={len(allowed)} sha256={digest[:16]}"
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"R1 PREPARE FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
