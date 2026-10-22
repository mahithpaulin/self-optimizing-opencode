"""Resumable machine state, append-only evidence, and a stale-safe runner lock."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


class RunnerBusy(RuntimeError):
    pass


class StateCorrupt(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _root(root: str | os.PathLike[str] | None) -> Path:
    return Path(root or Path(__file__).resolve().parent.parent).resolve()


def state_path(root: str | os.PathLike[str] | None = None) -> Path:
    return _root(root) / "state.json"


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.tmp-{os.getpid()}"
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def init_state(root: str | os.PathLike[str] | None = None, *, force: bool = False) -> dict:
    base = _root(root)
    path = state_path(base)
    if path.exists() and not force:
        return load_state(base)
    seed = json.loads((base / "config" / "initial_state.json").read_text(encoding="utf-8"))
    seed.setdefault("created_at", utc_now())
    seed["updated_at"] = utc_now()
    save_state(seed, base)
    return seed


def load_state(root: str | os.PathLike[str] | None = None) -> dict:
    base = _root(root)
    path = state_path(base)
    backup = path.with_suffix(".json.bak")
    for candidate in (path, backup):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("state is not an object")
            if candidate == backup and not path.exists():
                _atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")
            return data
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            if candidate == path:
                continue
            raise StateCorrupt(f"state and backup are unreadable: {exc}") from exc
    if path.exists() or backup.exists():
        raise StateCorrupt("state and backup are unreadable")
    return init_state(base)


def save_state(state: dict, root: str | os.PathLike[str] | None = None) -> dict:
    base = _root(root)
    path = state_path(base)
    if path.exists():
        try:
            json.loads(path.read_text(encoding="utf-8"))
            backup = path.with_suffix(".json.bak")
            _atomic_write(backup, path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    state["updated_at"] = utc_now()
    _atomic_write(path, json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state


def update_state(root: str | os.PathLike[str] | None = None, **changes: object) -> dict:
    state = load_state(root)
    state.update(changes)
    return save_state(state, root)


def append_state_md(title: str, lines: list[str], root: str | os.PathLike[str] | None = None) -> None:
    base = _root(root)
    path = base / "STATE.md"
    stamp = utc_now()
    block = [f"\n## {stamp} — {title}\n"]
    block.extend(f"- {line}" for line in lines)
    block.append("")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(block) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def append_history(record: dict, root: str | os.PathLike[str] | None = None) -> None:
    base = _root(root)
    path = base / "experiments" / "history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(record)
    record.setdefault("timestamp", utc_now())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_lock(
    root: str | os.PathLike[str] | None = None,
    *,
    stale_seconds: int = 21600,
) -> dict:
    base = _root(root)
    path = base / "logs" / "runner.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            old_pid = int(old.get("pid", -1))
            old_time = float(old.get("created_epoch", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            old_pid, old_time = -1, 0.0
        stale = not _pid_alive(old_pid) or (time.time() - old_time) > stale_seconds
        if not stale:
            raise RunnerBusy(f"runner already active with pid {old_pid}")
        stale_path = path.with_name(f"runner.lock.stale-{int(time.time())}")
        try:
            path.replace(stale_path)
        except OSError:
            pass
    token = {
        "pid": os.getpid(),
        "created_epoch": time.time(),
        "created_at": utc_now(),
        "host": os.uname().nodename,
    }
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RunnerBusy("runner lock appeared concurrently") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(token, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return token


def release_lock(token: dict, root: str | os.PathLike[str] | None = None) -> None:
    base = _root(root)
    path = base / "logs" / "runner.lock"
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return
    if int(current.get("pid", -1)) == int(token.get("pid", -2)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def stop_requested(root: str | os.PathLike[str] | None = None) -> bool:
    return (_root(root) / "STOP").exists()
