#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/phase5.install.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if data.get("schema") != 1 or not isinstance(data.get("files"), dict):
            raise RuntimeError("bad install manifest")
        for relative, expected in data["files"].items():
            path = ROOT / relative
            if not path.is_file():
                raise RuntimeError(f"missing: {relative}")
            if digest(path) != expected:
                raise RuntimeError(f"hash mismatch: {relative}")
        print(f"PHASE5-A INSTALL PASS: {len(data['files'])} delivered files match")
        return 0
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        print(f"PHASE5-A INSTALL FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
