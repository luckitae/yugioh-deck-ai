#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/r0.install.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> int:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if data.get("schema") != 1 or data.get("phase") != "R0" or not isinstance(data.get("files"), dict):
            raise RuntimeError("bad R0 install manifest")
        if not data["files"]:
            raise RuntimeError("empty R0 install manifest")
        for relative, expected in data["files"].items():
            if not isinstance(relative, str) or not isinstance(expected, str) or len(expected) != 64:
                raise RuntimeError("bad R0 install manifest entry")
            path = ROOT / relative
            if not path.is_file():
                raise RuntimeError(f"missing: {relative}")
            if digest(path) != expected:
                raise RuntimeError(f"hash mismatch: {relative}")
        print(f"R0 INSTALL PASS: {len(data['files'])} delivered files match")
        return 0
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        print(f"R0 INSTALL FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
