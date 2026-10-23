"""First-class optimization targets.

A target is a small, reviewable manifest: where the repository is, which branch
may be improved, which commands count as evidence, and which paths an automated
change may touch.  Targets are data, not code, so adding a repository does not
mean loosening the runner for every other repository.

The Python workspace runner in :mod:`tools.runner` remains the reference
implementation of the strategy.  A non-Python target such as a Rust workspace
uses this manifest plus its own bounded campaign driver
(:mod:`tools.axiom_campaign`), which applies the same rules: inspect, propose,
implement, test, measure, checkpoint, repeat.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ALLOWED_EXECUTABLES = {"cargo"}
REQUIRED_CONFIG = {
    "schema",
    "name",
    "repository",
    "target_branch",
    "optimization_branch_prefix",
    "allowed_edit_prefixes",
    "forbidden_edit_prefixes",
    "test_command",
    "doc_test_command",
    "format_command",
    "format_fix_command",
    "clippy_command",
    "benchmark_command",
    "limits",
}
REQUIRED_LIMITS = {
    "max_iterations",
    "max_model_seconds",
    "max_test_seconds",
    "max_bench_seconds",
    "max_patch_bytes",
    "max_changed_lines",
    "max_changed_files",
    "max_failure_streak",
    "min_remaining_seconds",
    "soak_seconds",
}
TASK_KINDS = {"test", "correctness", "performance", "feature", "docs", "tooling"}


class TargetError(ValueError):
    """A target manifest or backlog entry is not safe to execute."""


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TargetError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TargetError(f"{path} is not valid JSON: {exc}") from exc


def _normalize_prefix(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TargetError(f"{field} entries must be non-empty strings")
    prefix = value.strip().replace("\\", "/")
    if prefix.startswith("/") or ".." in Path(prefix).parts:
        raise TargetError(f"{field} entry {value!r} must be a relative path")
    if not prefix.endswith("/") and "." not in Path(prefix).name:
        prefix += "/"
    return prefix


def _validate_command(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise TargetError(f"{field} must be a non-empty list of strings")
    executable = Path(value[0]).name
    if executable not in ALLOWED_EXECUTABLES:
        raise TargetError(f"{field} executable {executable!r} is not allowed")
    if any("\n" in v or "\x00" in v for v in value):
        raise TargetError(f"{field} contains a control character")
    return list(value)


def validate_config(data: object, *, name: str) -> dict:
    if not isinstance(data, dict):
        raise TargetError("target config must be an object")
    missing = sorted(REQUIRED_CONFIG - set(data))
    if missing:
        raise TargetError(f"target config is missing: {', '.join(missing)}")
    if data["schema"] != 1:
        raise TargetError("target config schema must be 1")
    if data["name"] != name:
        raise TargetError(f"config name {data['name']!r} does not match directory {name!r}")
    if not isinstance(data["repository"], str) or not REPO_RE.match(data["repository"]):
        raise TargetError("repository must be owner/name")
    if not isinstance(data["target_branch"], str) or not data["target_branch"].strip():
        raise TargetError("target_branch is required")
    prefix = data["optimization_branch_prefix"]
    if not isinstance(prefix, str) or not prefix.endswith("/") or len(prefix) < 3:
        raise TargetError("optimization_branch_prefix must end with '/'")
    if data["optimization_branch_prefix"] == data["target_branch"]:
        raise TargetError("optimization branch prefix must not equal the target branch")
    allowed_raw = data["allowed_edit_prefixes"]
    if not isinstance(allowed_raw, list):
        raise TargetError("allowed_edit_prefixes must be a list")
    forbidden_raw = data["forbidden_edit_prefixes"]
    if not isinstance(forbidden_raw, list):
        raise TargetError("forbidden_edit_prefixes must be a list")
    allowed = [_normalize_prefix(v, "allowed_edit_prefixes") for v in allowed_raw]
    forbidden = [_normalize_prefix(v, "forbidden_edit_prefixes") for v in forbidden_raw]
    if not allowed:
        raise TargetError("allowed_edit_prefixes must be a non-empty list")
    if not forbidden:
        raise TargetError("forbidden_edit_prefixes must be a non-empty list")
    for required in (".github/", ".git/", "ai-runs/"):
        if required not in forbidden:
            raise TargetError(f"forbidden_edit_prefixes must contain {required!r}")
    overlap = sorted(set(allowed) & set(forbidden))
    if overlap:
        raise TargetError(f"paths cannot be both allowed and forbidden: {overlap}")

    config = dict(data)
    config["allowed_edit_prefixes"] = allowed
    config["forbidden_edit_prefixes"] = forbidden
    for field in (
        "test_command",
        "doc_test_command",
        "format_command",
        "format_fix_command",
        "clippy_command",
        "benchmark_command",
    ):
        config[field] = _validate_command(data[field], field)

    limits = data["limits"]
    if not isinstance(limits, dict):
        raise TargetError("limits must be an object")
    missing_limits = sorted(REQUIRED_LIMITS - set(limits))
    if missing_limits:
        raise TargetError(f"limits are missing: {', '.join(missing_limits)}")
    for field in REQUIRED_LIMITS:
        value = limits[field]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise TargetError(f"limits.{field} must be a positive integer")
    if not 1 <= limits["max_iterations"] <= 200:
        raise TargetError("limits.max_iterations out of bounds (1..200)")
    if limits["min_remaining_seconds"] >= limits["max_test_seconds"]:
        raise TargetError("min_remaining_seconds must be smaller than max_test_seconds")
    return config


def load_target(name: str, root: str | Path | None = None) -> dict:
    if not NAME_RE.match(name or ""):
        raise TargetError(f"invalid target name {name!r}")
    base = Path(root or ROOT).resolve()
    path = base / "targets" / name / "config.json"
    config = validate_config(_read_json(path), name=name)
    config["root"] = str(base)
    config["manifest_path"] = str(path)
    return config


def validate_task(task: object, *, config: dict) -> dict:
    if not isinstance(task, dict):
        raise TargetError("backlog entries must be objects")
    task_id = task.get("id")
    if not isinstance(task_id, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$", task_id):
        raise TargetError(f"invalid task id {task_id!r}")
    for field in ("title", "description"):
        if not isinstance(task.get(field), str) or not task[field].strip():
            raise TargetError(f"{task_id}: {field} is required")
    if task.get("kind") not in TASK_KINDS:
        raise TargetError(f"{task_id}: kind must be one of {sorted(TASK_KINDS)}")
    files = task.get("files", [])
    if not isinstance(files, list) or not all(isinstance(v, str) and v for v in files):
        raise TargetError(f"{task_id}: files must be a list of paths")
    for value in files:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in Path(normalized).parts:
            raise TargetError(f"{task_id}: file {value!r} must be relative")
        if not any(normalized.startswith(p) for p in config["allowed_edit_prefixes"]):
            raise TargetError(f"{task_id}: file {value!r} is outside the edit allowlist")
    if not isinstance(task.get("priority", 0), int) or isinstance(task.get("priority", 0), bool):
        raise TargetError(f"{task_id}: priority must be an integer")
    depends = task.get("depends_on", [])
    if not isinstance(depends, list) or not all(isinstance(v, str) for v in depends):
        raise TargetError(f"{task_id}: depends_on must be a list of task ids")
    if "patch" in task:
        patch = task["patch"]
        if not isinstance(patch, str) or patch.startswith("/") or ".." in Path(patch).parts:
            raise TargetError(f"{task_id}: patch must be a relative path")
    if task.get("deterministic_first") and "patch" not in task:
        raise TargetError(f"{task_id}: deterministic_first requires a patch")
    if "cargo_test" in task:
        _validate_command(task["cargo_test"], f"{task_id}.cargo_test")
    focus = task.get("focus", [])
    if not isinstance(focus, list):
        raise TargetError(f"{task_id}: focus must be a list")
    for entry in focus:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise TargetError(f"{task_id}: focus entries need a file")
        focus_path = entry["file"].replace("\\", "/")
        if focus_path.startswith("/") or ".." in Path(focus_path).parts:
            raise TargetError(f"{task_id}: focus file {focus_path!r} must be relative")
        if not any(focus_path.startswith(prefix) for prefix in config["allowed_edit_prefixes"]):
            raise TargetError(f"{task_id}: focus file {focus_path!r} is outside the edit allowlist")
        start, end = entry.get("start", 1), entry.get("end", 0)
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            raise TargetError(f"{task_id}: focus line range is invalid")
    out = dict(task)
    out["priority"] = int(task.get("priority", 0))
    out["files"] = list(files)
    out["depends_on"] = list(depends)
    out["deterministic_first"] = bool(task.get("deterministic_first", False))
    out["benchmark"] = bool(task.get("benchmark", False))
    metric = task.get("metric", "time")
    if metric not in {"time", "memory"}:
        raise TargetError(f"{task_id}: metric must be 'time' or 'memory'")
    out["metric"] = metric
    out["max_attempts"] = int(task.get("max_attempts", 2))
    if not 1 <= out["max_attempts"] <= 5:
        raise TargetError(f"{task_id}: max_attempts out of bounds (1..5)")
    return out


def load_backlog(name: str, root: str | Path | None = None) -> list[dict]:
    config = load_target(name, root)
    path = Path(config["root"]) / "targets" / name / "backlog.json"
    raw = _read_json(path)
    if not isinstance(raw, list) or not raw:
        raise TargetError("backlog must be a non-empty list")
    tasks = [validate_task(task, config=config) for task in raw]
    ids = [task["id"] for task in tasks]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        raise TargetError(f"duplicate task ids: {duplicates}")
    known = set(ids)
    for task in tasks:
        for dependency in task["depends_on"]:
            if dependency not in known:
                raise TargetError(f"{task['id']}: unknown dependency {dependency!r}")
    base = (Path(config["root"]) / "targets" / name).resolve()
    for task in tasks:
        if "patch" not in task:
            continue
        patch = (base / task["patch"]).resolve()
        if base not in patch.parents:
            raise TargetError(f"{task['id']}: patch escapes the target directory")
        if not patch.is_file():
            raise TargetError(f"{task['id']}: patch does not exist: {task['patch']}")
    tasks.sort(key=lambda task: (task["priority"], task["id"]))
    return tasks
