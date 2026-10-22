"""Create and verify recoverable snapshots without overwriting live state."""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
import tempfile
from pathlib import Path

from tools import state as state_mod
from tools.security import ROOT, Workspace

EXCLUDED_PARTS = {".git", "sandbox", "checkpoints", "__pycache__", "node_modules"}


def _safe_name(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-")
    return cleaned[:48] or "checkpoint"


def _included(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    return not (path.suffix == ".pyc" or path.name.endswith(".tar.gz"))


def create(label: str = "manual", root: str | Path | None = None) -> dict:
    ws = Workspace(root or ROOT)
    stamp = state_mod.utc_now().replace(":", "").replace("-", "")
    name = f"ckpt-{stamp}-{_safe_name(label)}"
    target = ws.root / "checkpoints" / f"{name}.tar.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    files = [path for path in ws.files() if _included(path, ws.root)]
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as handle:
        temp = Path(handle.name)
    try:
        with tarfile.open(temp, "w:gz") as archive:
            for path in sorted(files):
                archive.add(path, arcname=path.relative_to(ws.root).as_posix(), recursive=False)
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {
        "schema": 1,
        "label": label,
        "name": name,
        "created_at": state_mod.utc_now(),
        "archive": target.relative_to(ws.root).as_posix(),
        "sha256": digest,
        "size_bytes": target.stat().st_size,
        "file_count": len(files),
        "files": [path.relative_to(ws.root).as_posix() for path in sorted(files)],
    }
    ws.write_json(f"checkpoints/{name}.json", manifest)
    return manifest


def verify(manifest_path: str | Path, root: str | Path | None = None) -> dict:
    ws = Workspace(root or ROOT)
    manifest = json.loads(ws.read_text(manifest_path))
    archive = ws.resolve(manifest["archive"])
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    members = []
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"unsafe checkpoint member: {name}")
            members.append(name)
    ok = digest == manifest["sha256"] and len(members) == manifest["file_count"]
    return {
        "ok": ok,
        "sha256": digest,
        "expected_sha256": manifest["sha256"],
        "members": len(members),
        "expected_members": manifest["file_count"],
        "archive": manifest["archive"],
    }


def extract(manifest_path: str | Path, destination: str | Path, root: str | Path | None = None) -> dict:
    ws = Workspace(root or ROOT)
    manifest = json.loads(ws.read_text(manifest_path))
    dest = ws.resolve(destination, for_write=True)
    dest.mkdir(parents=True, exist_ok=True)
    archive = ws.resolve(manifest["archive"])
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise ValueError(f"unsafe checkpoint member: {member.name}")
        tar.extractall(dest, filter="data")
    return {"ok": True, "destination": str(dest), "members": len(manifest["files"])}
