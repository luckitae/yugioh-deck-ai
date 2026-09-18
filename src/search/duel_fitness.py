"""Phase 5-C 실제 OCGCore 반복 듀얼 평가.

실제 runner 결과만 집계한다. runner timeout/unsupported/protocol/resource 오류는 절대로
승리로 바꾸지 않으며, 해당 덱의 ``score_ppm``을 -1로 만들어 완전한 평가보다 아래에 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from deck.rules import SECTIONS, json_text, read_json, ydk_text

PPM = 1_000_000
_ALLOWED_SPLITS = {"training", "validation", "final"}
_ID = re.compile(r"[A-Za-z0-9._-]{1,80}\Z")


class DuelFitnessError(ValueError):
    """상대 Pool/스케줄/runner 결과가 평가에 사용할 수 없음."""


@dataclass(frozen=True)
class Opponent:
    id: str
    file: Path
    splits: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class DuelSchedule:
    seeds: tuple[int, ...]
    max_calls: int = 200000
    timeout_seconds: int = 90

    def validate(self) -> None:
        if not self.seeds or len(self.seeds) > 128:
            raise DuelFitnessError("duel schedule requires 1..128 seeds")
        if len(set(self.seeds)) != len(self.seeds):
            raise DuelFitnessError("duel seeds must be unique")
        for seed in self.seeds:
            if type(seed) is not int or not 0 <= seed <= (1 << 64) - 1:
                raise DuelFitnessError("duel seed must be uint64")
        if type(self.max_calls) is not int or not 1 <= self.max_calls <= 1_000_000:
            raise DuelFitnessError("max_calls must be 1..1000000")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 3600:
            raise DuelFitnessError("timeout_seconds must be 1..3600")


def parse_seeds(text: str) -> tuple[int, ...]:
    if not isinstance(text, str) or not text.strip():
        raise DuelFitnessError("duel seeds are empty")
    out: list[int] = []
    for raw in text.split(","):
        token = raw.strip()
        if not token or not token.isascii() or not token.isdecimal():
            raise DuelFitnessError("duel seeds must be comma-separated unsigned integers")
        value = int(token)
        if not 0 <= value <= (1 << 64) - 1:
            raise DuelFitnessError("duel seed must be uint64")
        out.append(value)
    result = tuple(out)
    DuelSchedule(result).validate()
    return result


def _safe_relative(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise DuelFitnessError(f"{label}: invalid path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise DuelFitnessError(f"{label}: path must stay inside opponent pool directory")
    return path


def load_opponent_pool(path: Path, split: str) -> tuple[dict[str, Any], list[Opponent]]:
    if split not in _ALLOWED_SPLITS:
        raise DuelFitnessError("opponent split must be training, validation, or final")
    if not path.is_file():
        raise DuelFitnessError(f"opponent manifest missing: {path}")
    try:
        payload = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise DuelFitnessError(f"opponent manifest read error: {error}") from error
    expected = {"schema", "id", "kind", "note", "decks"}
    if not isinstance(payload, dict) or set(payload) != expected or payload.get("schema") != 1:
        raise DuelFitnessError("opponent manifest: unsupported schema/fields")
    if not isinstance(payload["id"], str) or not _ID.fullmatch(payload["id"]):
        raise DuelFitnessError("opponent manifest: invalid id")
    if payload["kind"] not in ("test-only", "custom", "pinned-snapshot"):
        raise DuelFitnessError("opponent manifest: invalid kind")
    if not isinstance(payload["note"], str) or not payload["note"].strip():
        raise DuelFitnessError("opponent manifest: nonempty note required")
    rows = payload["decks"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise DuelFitnessError("opponent manifest: decks must contain 1..256 rows")
    seen: set[str] = set()
    selected: list[Opponent] = []
    for row in rows:
        fields = {"id", "file", "splits", "note"}
        if not isinstance(row, dict) or set(row) != fields:
            raise DuelFitnessError("opponent row: invalid fields")
        oid = row["id"]
        if not isinstance(oid, str) or not _ID.fullmatch(oid) or oid in seen:
            raise DuelFitnessError("opponent row: invalid/duplicate id")
        seen.add(oid)
        splits = row["splits"]
        if (not isinstance(splits, list) or not splits or len(splits) != len(set(splits)) or
                any(item not in _ALLOWED_SPLITS for item in splits)):
            raise DuelFitnessError("opponent row: invalid split list")
        if not isinstance(row["note"], str) or not row["note"].strip():
            raise DuelFitnessError("opponent row: nonempty note required")
        relative = _safe_relative(row["file"], "opponent row")
        base = path.parent.resolve()
        full = (base / relative).resolve()
        if full != base and base not in full.parents:
            raise DuelFitnessError("opponent row: resolved path escapes pool directory")
        if not full.is_file():
            raise DuelFitnessError(f"opponent deck missing: {relative.as_posix()}")
        if split in splits:
            selected.append(Opponent(oid, full, tuple(sorted(splits)), row["note"]))
    if not selected:
        raise DuelFitnessError(f"opponent pool has no decks in split={split}")
    return payload, sorted(selected, key=lambda row: row.id)


def _rate(wins: int, total: int) -> int | None:
    return None if total <= 0 else wins * PPM // total


def _breakdown(cases: list[dict[str, Any]]) -> dict[str, Any]:
    scheduled = len(cases)
    finished = [row for row in cases if row.get("status") == "finished"]
    wins = sum(row.get("outcome") == "win" for row in finished)
    draws = sum(row.get("outcome") == "draw" for row in finished)
    losses = sum(row.get("outcome") == "loss" for row in finished)
    failures = scheduled - len(finished)
    complete = failures == 0 and scheduled > 0
    return {
        "scheduled_duels": scheduled,
        "finished_duels": len(finished),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "failures": failures,
        "completion_rate_ppm": 0 if scheduled == 0 else len(finished) * PPM // scheduled,
        "win_rate_ppm": _rate(wins, scheduled) if complete else None,
        "draw_rate_ppm": _rate(draws, scheduled) if complete else None,
        "nonloss_rate_ppm": _rate(wins + draws, scheduled) if complete else None,
    }


def aggregate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(cases, list) or not cases:
        raise DuelFitnessError("cannot aggregate an empty duel schedule")
    for row in cases:
        if not isinstance(row, dict):
            raise DuelFitnessError("duel case must be an object")
        if row.get("seat") not in (0, 1) or not isinstance(row.get("opponent_id"), str):
            raise DuelFitnessError("duel case missing seat/opponent")
        if row.get("status") == "finished" and row.get("outcome") not in ("win", "draw", "loss"):
            raise DuelFitnessError("finished duel case has invalid outcome")
    overall = _breakdown(cases)
    complete = overall["failures"] == 0
    per_seat = {
        "going_first": _breakdown([row for row in cases if row["seat"] == 0]),
        "going_second": _breakdown([row for row in cases if row["seat"] == 1]),
    }
    opponents = sorted({row["opponent_id"] for row in cases})
    per_opponent = {oid: _breakdown([row for row in cases if row["opponent_id"] == oid]) for oid in opponents}
    complete_rates = [row["win_rate_ppm"] for row in per_opponent.values() if row["win_rate_ppm"] is not None]
    turns = [int(row["turns"]) for row in cases if row.get("status") == "finished" and type(row.get("turns")) is int]
    # 실제 승률만 fitness의 1순위로 사용한다. 불완전 평가는 어떤 승수도 fitness로 인정하지 않는다.
    score = overall["win_rate_ppm"] if complete else -1
    return {
        "fitness_kind": "real-ocgcore-win-rate-v1",
        "score_ppm": score,
        "win_rate_evaluated": complete,
        **overall,
        "going_first": per_seat["going_first"],
        "going_second": per_seat["going_second"],
        "per_opponent": per_opponent,
        "worst_opponent_win_rate_ppm": min(complete_rates) if complete and complete_rates else None,
        "mean_turns_milli": None if not turns else sum(turns) * 1000 // len(turns),
    }


def _required_flags(required: dict[str, dict[int, int]], seat: int) -> list[str]:
    if not isinstance(required, dict) or set(required) != {"main", "extra"}:
        raise DuelFitnessError("required must contain main/extra")
    out: list[str] = []
    for section in ("main", "extra"):
        counts = required[section]
        if not isinstance(counts, dict):
            raise DuelFitnessError("required counts must be objects")
        for code, count in sorted(counts.items()):
            if type(code) is not int or not 1 <= code <= 0xFFFFFFFF or type(count) is not int or not 1 <= count <= 3:
                raise DuelFitnessError("invalid required card/count")
            out += [f"--required-{section}{seat}", f"{code}={count}"]
    return out


def _deck_fingerprint(deck: dict[str, list[int]]) -> str:
    body = {section: list(deck[section]) for section in SECTIONS}
    return hashlib.sha256(json_text(body).encode("utf-8")).hexdigest()


class DuelEvaluator:
    """``search.ga.run_search``가 호출할 수 있는 실제 duel evaluator.

    같은 덱 identity는 현재 evaluator 인스턴스에서 한 번만 실행하고 캐시한다.
    """

    def __init__(self, runner: Path, db: Path, scripts: Path, opponents: list[Opponent],
                 schedule: DuelSchedule, required: dict[str, dict[int, int]], work_dir: Path):
        schedule.validate()
        if not runner.is_file() or not db.is_file() or not scripts.is_dir():
            raise DuelFitnessError("runner/DB/scripts prerequisite missing")
        if not opponents:
            raise DuelFitnessError("at least one opponent is required")
        self.runner = runner.resolve()
        self.db = db.resolve()
        self.scripts = scripts.resolve()
        self.opponents = list(opponents)
        self.schedule = schedule
        self.required = required
        self.work_dir = work_dir
        self.deck_dir = work_dir / "decks"
        self.case_dir = work_dir / "cases"
        self.eval_dir = work_dir / "evaluations"
        for directory in (self.deck_dir, self.case_dir, self.eval_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.cache: dict[str, dict[str, Any]] = {}
        self.runner_invocations = 0

    def _run_case(self, fingerprint: str, candidate: Path, opponent: Opponent,
                  seed: int, seat: int) -> dict[str, Any]:
        case_id = f"{fingerprint[:16]}__{opponent.id}__seed{seed}__seat{seat}"
        result_path = self.case_dir / f"{case_id}.json"
        trace_path = self.case_dir / f"{case_id}.jsonl"
        log_path = self.case_dir / f"{case_id}.log"
        deck0, deck1 = (candidate, opponent.file) if seat == 0 else (opponent.file, candidate)
        command = [str(self.runner), "--db", str(self.db), "--scripts", str(self.scripts),
                   "--deck0", str(deck0), "--deck1", str(deck1), "--seed", str(seed),
                   "--policy", "first-legal-v1", "--max-calls", str(self.schedule.max_calls),
                   "--result", str(result_path), "--trace", str(trace_path)]
        command += _required_flags(self.required, seat)
        self.runner_invocations += 1
        status = "runner_error"
        error = ""
        payload: dict[str, Any] | None = None
        try:
            completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       timeout=self.schedule.timeout_seconds)
            log_path.write_text(completed.stdout, encoding="utf-8")
            if result_path.is_file():
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            if completed.returncode != 0:
                status = str(payload.get("status")) if isinstance(payload, dict) else "runner_error"
                error = str(payload.get("error", "")) if isinstance(payload, dict) else f"runner exit {completed.returncode}"
            elif not isinstance(payload, dict):
                status = "missing_result"
                error = "runner returned success without result JSON"
            elif payload.get("status") != "finished" or payload.get("winner") not in (0, 1, 2):
                status = str(payload.get("status", "invalid_result"))
                error = str(payload.get("error", ""))
            elif payload.get("engine_errors") != 0:
                status = "engine_error"
                error = "runner reported engine script errors"
            elif payload.get("seed") != seed or payload.get("first_player") != 0 or payload.get("policy") != "first-legal-v1":
                status = "provenance_error"
                error = "runner result seed/first-player/policy mismatch"
            elif type(payload.get("turns")) is not int or payload["turns"] <= 0 or type(payload.get("selections")) is not int or payload["selections"] <= 0:
                status = "invalid_result"
                error = "finished runner result did not exercise turns/selections"
            elif not trace_path.is_file() or trace_path.stat().st_size == 0:
                status = "missing_trace"
                error = "finished runner result has no trace"
            else:
                status = "finished"
        except subprocess.TimeoutExpired as timeout:
            text = timeout.stdout if isinstance(timeout.stdout, str) else ""
            log_path.write_text(text or "TIMEOUT\n", encoding="utf-8")
            status = "timeout"
            error = "duel runner timeout"
        except (OSError, ValueError, json.JSONDecodeError) as run_error:
            log_path.write_text(str(run_error) + "\n", encoding="utf-8")
            status = "runner_error"
            error = str(run_error)

        winner = payload.get("winner") if status == "finished" and isinstance(payload, dict) else None
        if winner == 2:
            outcome = "draw"
        elif winner == seat:
            outcome = "win"
        elif winner in (0, 1):
            outcome = "loss"
        else:
            outcome = None
        return {
            "opponent_id": opponent.id,
            "seed": seed,
            "seat": seat,
            "candidate_first": seat == 0,
            "status": status,
            "outcome": outcome,
            "winner": winner,
            "turns": payload.get("turns") if isinstance(payload, dict) else None,
            "selections": payload.get("selections") if isinstance(payload, dict) else None,
            "error": error,
            "result_file": result_path.relative_to(self.work_dir).as_posix() if result_path.is_file() else None,
            "trace_file": trace_path.relative_to(self.work_dir).as_posix() if trace_path.is_file() else None,
            "log_file": log_path.relative_to(self.work_dir).as_posix(),
        }

    def __call__(self, deck: dict[str, list[int]]) -> dict[str, Any]:
        for section in SECTIONS:
            if section not in deck or not isinstance(deck[section], list):
                raise DuelFitnessError("candidate deck missing section")
        fingerprint = _deck_fingerprint(deck)
        if fingerprint in self.cache:
            return self.cache[fingerprint]
        candidate = self.deck_dir / f"{fingerprint}.ydk"
        candidate.write_text(
            ydk_text({section: deck[section] for section in SECTIONS}).replace(
                "#created by yugioh-deck-ai phase4; NOT a win-rate result",
                "#created by yugioh-deck-ai phase5-c evaluator", 1),
            encoding="utf-8", newline="\n",
        )
        cases: list[dict[str, Any]] = []
        for opponent in self.opponents:
            for seed in self.schedule.seeds:
                for seat in (0, 1):
                    cases.append(self._run_case(fingerprint, candidate, opponent, seed, seat))
        metrics = aggregate_cases(cases)
        record = {"schema": 1, "deck_fingerprint": fingerprint, "metrics": metrics, "cases": cases}
        (self.eval_dir / f"{fingerprint}.json").write_text(json_text(record), encoding="utf-8", newline="\n")
        # run_search는 metrics만 필요하다. cases는 별도 evaluation JSON에 저장해 population manifest 폭증을 막는다.
        result = {**metrics, "evaluation_file": (self.eval_dir / f"{fingerprint}.json").relative_to(self.work_dir).as_posix()}
        self.cache[fingerprint] = result
        return result
