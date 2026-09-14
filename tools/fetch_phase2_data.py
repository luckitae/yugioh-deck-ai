#!/usr/bin/env python3
"""Linux/Actions 전용. lock에 고정된 원본만 가져오며 가짜 데이터로 대체하지 않는다."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_URLS = {
    "core": "https://github.com/edo9300/ygopro-core.git",
    "database": "https://github.com/ProjectIgnis/BabelCDB.git",
    "scripts": "https://github.com/ProjectIgnis/CardScripts.git",
}


def git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args], check=True,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240,
    )
    return result.stdout.strip()


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def checkout(directory: Path, spec: dict) -> str:
    """기존 폴더를 지우거나 reset하지 않는다. 다른 버전/로컬 수정이면 중단한다."""
    if directory.exists():
        if not (directory / ".git").is_dir():
            raise RuntimeError(f"Refusing to overwrite non-repository: {directory}")
        if git(directory, "remote", "get-url", "origin") != spec["url"]:
            raise RuntimeError(f"Unexpected origin: {directory}")
        if git(directory, "status", "--porcelain"):
            raise RuntimeError(f"Repository has local changes: {directory}")
        if git(directory, "rev-parse", "HEAD") != spec["commit"]:
            raise RuntimeError(f"Pinned revision mismatch: {directory}")
    else:
        directory.mkdir(parents=True)
        git(directory, "init")
        git(directory, "remote", "add", "origin", spec["url"])
        git(directory, "fetch", "--depth=1", "origin", spec["commit"])
        git(directory, "checkout", "--detach", "FETCH_HEAD")
    actual = git(directory, "rev-parse", "HEAD")
    if actual != spec["commit"]:
        raise RuntimeError(f"Commit verification failed: {directory}")
    print(f"Pinned {directory.name}: {actual}", flush=True)
    return actual


def main() -> int:
    artifact = ROOT / "artifacts"
    artifact.mkdir(exist_ok=True)
    try:
        lock = json.loads((ROOT / "data/phase2.lock.json").read_text(encoding="utf-8"))
        if lock.get("schema") != 1 or lock.get("engine_api") != "11.0":
            raise RuntimeError("Unsupported lock schema/API")
        for key, url in EXPECTED_URLS.items():
            spec = lock[key]
            if spec.get("url") != url or not re.fullmatch(r"[0-9a-f]{40}", spec.get("commit", "")):
                raise RuntimeError(f"Invalid dependency lock: {key}")
        if lock["database"].get("file") != "cards.cdb":
            raise RuntimeError("Only the pinned cards.cdb is supported")
        core = ROOT / "ygopro-core"
        if git(core, "rev-parse", "HEAD") != lock["core"]["commit"]:
            raise RuntimeError("Core checkout does not match phase2.lock.json")
        vendor = ROOT / "data/vendor"
        db_repo, script_repo = vendor / "BabelCDB", vendor / "CardScripts"
        db_commit = checkout(db_repo, lock["database"])
        script_commit = checkout(script_repo, lock["scripts"])
        db_path = db_repo / "cards.cdb"
        if not db_path.is_file():
            raise RuntimeError("Pinned repository has no cards.cdb")
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            schema = [row[1] for row in connection.execute("PRAGMA table_info(datas)")]
            required = {"id", "ot", "alias", "setcode", "type", "atk", "def", "level", "race", "attribute", "category"}
            if not required.issubset(schema):
                raise RuntimeError("Unsupported datas schema")
            count = connection.execute("SELECT COUNT(*) FROM datas").fetchone()[0]
            hinotama = connection.execute("SELECT id, type FROM datas WHERE id=46130346").fetchone()
            if not count or hinotama != (46130346, 2):
                raise RuntimeError("Database smoke fixture card is missing or has changed type")
        finally:
            connection.close()
        for relative in ("constant.lua", "utility.lua", "official/c46130346.lua", "unofficial/proc_unofficial.lua"):
            if not (script_repo / relative).is_file():
                raise RuntimeError(f"Required pinned script is missing: {relative}")
        script_hashes = {}
        for path in sorted(script_repo.rglob("*.lua")):
            if ".git" in path.relative_to(script_repo).parts:
                continue
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"Unexpected script entry: {path}")
            script_hashes[path.relative_to(script_repo).as_posix()] = sha256(path)
        digest = hashlib.sha256()
        for name, value in script_hashes.items():
            digest.update(f"{name}\0{value}\n".encode("utf-8"))
        manifest = {
            "schema": 1, "lock": lock,
            "actual_commits": {"core": git(core, "rev-parse", "HEAD"), "database": db_commit, "scripts": script_commit},
            "cards_cdb_sha256": sha256(db_path), "database_records": count,
            "lua_count": len(script_hashes), "lua_tree_sha256": digest.hexdigest(),
            "lua_files_sha256": script_hashes,
        }
        (artifact / "data_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"PHASE2 DATA READY: {count} DB rows, {len(script_hashes)} Lua files", flush=True)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        message = str(error)
        if isinstance(error, subprocess.CalledProcessError):
            message += "\n" + (error.stderr or "")
        (artifact / "data_fetch_error.txt").write_text(message + "\n", encoding="utf-8")
        print(f"PHASE2 DATA FAIL: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
