"""Bounded, zero-cost proposal call using the official V1 free-tier client.

V2.1.2 is installed and its checksum is recorded, but its hosted free tier returns
403 for this account/network. The V1 client is official, already present, and the
same free model succeeds there. No paid provider or key is used.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from tools import state as state_mod
from tools.security import ROOT, Workspace

REQUIRED = ("weakness", "hypothesis", "metric", "change", "risk", "reversible")
FORBIDDEN = (
    "paid",
    "billing",
    "purchase",
    "deploy",
    "publish",
    "push",
    "network",
    "curl",
    "wget",
    "ssh",
    "api key",
)


def free_mb() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


def _clean(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _text_from_events(raw: str) -> str:
    chunks: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            chunks.append(line)
            continue
        part = event.get("part") or {}
        if event.get("type") == "text" and isinstance(part.get("text"), str):
            chunks.append(part["text"])
    return _clean("\n".join(chunks) if chunks else raw)


def parse(raw: str) -> dict:
    text = _text_from_events(raw)
    candidates = [text]
    for match in re.finditer(r"\{.*\}", text, re.DOTALL):
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        if all(key in value for key in REQUIRED) and isinstance(value.get("reversible"), bool):
            value["_raw_text"] = text
            return value
    raise ValueError("model did not return a valid proposal JSON object")


def call(summary: str, root: str | Path | None = None, timeout: int = 180) -> dict:
    ws = Workspace(root or ROOT)
    available = free_mb()
    if available < 250:
        return {"ok": False, "error": f"insufficient free memory: {available} MB"}
    prompt = (
        "Read the evidence summary below. Return exactly one JSON proposal with keys "
        "weakness, hypothesis, metric, change, risk, reversible (boolean), and "
        "expected_files (array). Do not use tools. Do not add prose.\n\n"
        f"EVIDENCE\n{summary[:6000]}"
    )
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [str(ws.root / "tools" / "modelrun"), prompt],
            cwd=ws.root,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=timeout + 30,
        )
    except OSError as exc:
        output = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        ws.write_json(f"proposals/{state_mod.utc_now().replace(':', '')}-error.json", output)
        return output
    except subprocess.TimeoutExpired as exc:
        output = {
            "ok": False,
            "error": f"model timeout after {timeout}s",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "stdout": (exc.stdout or "")[:2000] if isinstance(exc.stdout, str) else "",
        }
        ws.write_json(f"proposals/{state_mod.utc_now().replace(':', '')}-error.json", output)
        return output
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    record = {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "elapsed_ms": elapsed_ms,
        "stdout": completed.stdout[-12000:],
        "stderr": completed.stderr[-2000:],
        "free_mb_before": available,
    }
    try:
        proposal = parse(completed.stdout)
        bad = [
            word
            for word in FORBIDDEN
            if word in json.dumps(proposal, ensure_ascii=False).lower() and word not in {"network"}
        ]
        if bad:
            proposal["_flags"] = bad
        record["proposal"] = proposal
    except Exception as exc:
        record["ok"] = False
        record["error"] = f"{type(exc).__name__}: {exc}"
    path = f"proposals/{state_mod.utc_now().replace(':', '')}-model.json"
    ws.write_json(path, record)
    record["path"] = path
    return record
