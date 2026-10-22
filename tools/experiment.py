"""Proposal validation, acceptance rules, promotion, and rollback."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

from tools import state as state_mod
from tools.security import ROOT, SecurityError, Workspace

REQUIRED = ("id", "title", "weakness", "hypothesis", "candidate", "target", "acceptance")


def load(experiment_id: str, root: str | Path | None = None) -> dict:
    ws = Workspace(root or ROOT)
    path = ws.resolve(f"experiments/{experiment_id}/proposal.json")
    proposal = json.loads(ws.read_text(path))
    validate(proposal)
    return proposal


def validate(proposal: dict) -> None:
    for key in REQUIRED:
        if key not in proposal:
            raise ValueError(f"proposal missing {key}")
    if not str(proposal["candidate"]).startswith("experiments/"):
        raise ValueError("candidate must live under experiments/")
    if not str(proposal["target"]).startswith("tools/"):
        raise ValueError("target must live under tools/")
    if proposal["target"].endswith(("security.py", "bench.py", "runner.py", "state.py")):
        raise ValueError("target is a protected orchestration/security file")
    acceptance = proposal["acceptance"]
    for key in ("min_correctness", "max_latency_ratio", "max_cold_ratio"):
        if key not in acceptance:
            raise ValueError(f"acceptance missing {key}")


def evaluate(
    proposal: dict,
    baseline: dict,
    candidate: dict,
    *,
    tests_ok: bool,
    corpus_ok: bool = True,
) -> dict:
    acceptance = proposal["acceptance"]
    reasons: list[str] = []
    baseline_ms = float(baseline.get("median_batch_ms") or 0.0)
    candidate_ms = float(candidate.get("median_batch_ms") or 0.0)
    cold_ms = float(candidate.get("cold_batch_ms") or 0.0)
    warm_ratio = round(candidate_ms / baseline_ms, 4) if baseline_ms > 0 else None
    cold_ratio = round(cold_ms / baseline_ms, 4) if baseline_ms > 0 else None
    if candidate.get("correctness", 0.0) < float(acceptance["min_correctness"]):
        reasons.append(
            f"correctness {candidate.get('correctness')} < {acceptance['min_correctness']}"
        )
    if candidate.get("failed_queries"):
        reasons.append(f"failed queries: {candidate['failed_queries']}")
    if not corpus_ok:
        reasons.append("corpus hash differs from the frozen benchmark")
    if not tests_ok:
        reasons.append("test suite is not green")
    if warm_ratio is None or warm_ratio > float(acceptance["max_latency_ratio"]):
        reasons.append(f"warm latency ratio {warm_ratio} > {acceptance['max_latency_ratio']}")
    if cold_ratio is None or cold_ratio > float(acceptance["max_cold_ratio"]):
        reasons.append(f"cold latency ratio {cold_ratio} > {acceptance['max_cold_ratio']}")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "baseline_median_batch_ms": baseline_ms,
        "candidate_median_batch_ms": candidate_ms,
        "baseline_cold_batch_ms": baseline.get("cold_batch_ms"),
        "candidate_cold_batch_ms": cold_ms,
        "warm_ratio": warm_ratio,
        "cold_ratio": cold_ratio,
        "tests_ok": tests_ok,
        "correctness": candidate.get("correctness"),
    }


def promote(proposal: dict, root: str | Path | None = None) -> dict:
    ws = Workspace(root or ROOT)
    candidate_path = ws.resolve(proposal["candidate"])
    target = ws.resolve(proposal["target"], for_write=True)
    source = ws.read_text(candidate_path)
    compile(source, str(target), "exec")
    previous = ws.read_text(target)
    backup_rel = f"rollback/{proposal['id']}-{target.name}.bak"
    ws.write_text(backup_rel, previous, allow_protected=True)
    diff = "".join(
        difflib.unified_diff(
            previous.splitlines(True),
            source.splitlines(True),
            fromfile=f"a/{proposal['target']}",
            tofile=f"b/{proposal['target']}",
        )
    )
    ws.write_text(f"experiments/{proposal['id']}/diff.patch", diff)
    ws.write_text(target, source)
    return {
        "promoted": True,
        "target": proposal["target"],
        "backup": backup_rel,
        "candidate": proposal["candidate"],
        "diff": f"experiments/{proposal['id']}/diff.patch",
        "promoted_at": state_mod.utc_now(),
    }


def rollback(proposal: dict, backup: str, root: str | Path | None = None) -> dict:
    ws = Workspace(root or ROOT)
    previous = ws.read_text(backup)
    ws.write_text(proposal["target"], previous)
    return {"rolled_back": True, "target": proposal["target"], "backup": backup}


def record(proposal: dict, result: dict, root: str | Path | None = None) -> Path:
    ws = Workspace(root or ROOT)
    return ws.write_json(f"experiments/{proposal['id']}/result.json", result)
