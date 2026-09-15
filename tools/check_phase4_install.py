#!/usr/bin/env python3
"""iPad/a-Shell용 교체본 검사. SQLite/컴파일러 없이 파일 SHA-256만 검사한다."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    try:
        manifest = json.loads((ROOT / "data/phase4.install.json").read_text(encoding="utf-8"))
        if manifest.get("schema") != 1 or manifest.get("stage") != "phase4-first-delivery":
            raise ValueError("unknown install manifest")
        errors = []
        checked = 0
        for group in ("updated", "preserved"):
            entries = manifest[group]
            if not isinstance(entries, dict) or not entries:
                raise ValueError("empty/invalid install manifest")
            for relative, expected in entries.items():
                rel = Path(relative)
                if rel.is_absolute() or ".." in rel.parts or not isinstance(expected, str) or len(expected) != 64:
                    raise ValueError("unsafe/invalid install entry")
                path = ROOT / rel
                if not path.is_file():
                    errors.append(f"MISSING {relative}")
                    continue
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if actual != expected:
                    errors.append(f"DIFFERENT {relative} ({group})")
                checked += 1
        if errors:
            print("PHASE4 INSTALL FAIL:\n" + "\n".join(errors), file=sys.stderr)
            print("Do not commit yet. Check extraction location or independently modified files.", file=sys.stderr)
            return 1
        print(f"PHASE4 INSTALL PASS: {checked} files; updated delivery and Phase 1/2/3 sources match")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"PHASE4 INSTALL FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
