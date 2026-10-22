"""Filesystem confinement, command allowlisting, and bounded subprocesses.

This module is the enforcement point for every worker action. It is deliberately
small and dependency-free. It does not claim to be a container: the host is an
Android device without user namespaces, so confinement is realpath-based plus an
executable allowlist, resource limits, and environment sanitisation.
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import signal
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent


class SecurityError(PermissionError):
    """A request crossed a declared boundary."""


class CommandDenied(SecurityError):
    """A subprocess request was not on the allowlist."""


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class Workspace:
    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(root or ROOT).resolve()
        self.limits = _load_json(self.root / "config" / "limits.json")
        self.policy = _load_json(self.root / "config" / "permissions.json")
        self._sandbox_home = self.root / "sandbox" / "home"
        self._sandbox_tmp = self.root / "sandbox" / "tmp"
        self._sandbox_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._sandbox_tmp.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _inside(self, path: Path) -> bool:
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    def _secret(self, rel: str, name: str) -> bool:
        lowered = name.lower()
        for fragment in self.policy.get("secret_name_fragments", []):
            if fragment.lower() in lowered:
                return True
        parts = PurePosixPath(rel).parts
        if ".git" in parts or ".ssh" in parts or ".gnupg" in parts:
            return True
        return False

    def _protected(self, rel: str) -> bool:
        for prefix in self.policy.get("protected_write_prefixes", []):
            clean = prefix.rstrip("/")
            if rel == clean or rel.startswith(clean + "/"):
                return True
        return False

    def resolve(
        self,
        path: str | os.PathLike[str],
        *,
        for_write: bool = False,
        allow_protected: bool = False,
    ) -> Path:
        raw = os.fspath(path)
        if not isinstance(raw, str) or not raw:
            raise SecurityError("empty or non-string path")
        if "\x00" in raw or "\n" in raw:
            raise SecurityError("control character in path")
        if raw.startswith("~") or "$" in raw:
            raise SecurityError("home/environment expansion is not permitted")
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        real = Path(os.path.realpath(candidate))
        if not self._inside(real):
            raise SecurityError(f"path escapes workspace: {raw}")
        rel = real.relative_to(self.root).as_posix()
        if self._secret(rel, real.name) or self._secret(raw, Path(raw).name):
            raise SecurityError(f"secret or repository metadata path denied: {raw}")
        if for_write and not allow_protected and self._protected(rel):
            raise SecurityError(f"protected path is read-only to the worker: {rel}")
        return real

    def read_bytes(self, path: str | os.PathLike[str]) -> bytes:
        real = self.resolve(path)
        if not real.is_file():
            raise SecurityError(f"not a regular file: {path}")
        limit = int(self.limits["max_read_bytes"])
        size = real.stat().st_size
        if size > limit:
            raise SecurityError(f"file exceeds read limit ({size} > {limit})")
        with real.open("rb") as handle:
            return handle.read(limit + 1)

    def read_text(self, path: str | os.PathLike[str]) -> str:
        try:
            return self.read_bytes(path).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecurityError(f"file is not UTF-8 text: {path}") from exc

    def write_text(
        self,
        path: str | os.PathLike[str],
        data: str,
        *,
        allow_protected: bool = False,
    ) -> Path:
        encoded = data.encode("utf-8")
        if len(encoded) > int(self.limits["max_write_bytes"]):
            raise SecurityError("write exceeds max_write_bytes")
        real = self.resolve(path, for_write=True, allow_protected=allow_protected)
        real.parent.mkdir(parents=True, exist_ok=True)
        temp = real.parent / f".{real.name}.tmp-{os.getpid()}"
        try:
            with temp.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, real)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        return real

    def write_json(self, path: str | os.PathLike[str], obj: object, **kwargs: object) -> Path:
        return self.write_text(path, json.dumps(obj, indent=2, sort_keys=True) + "\n", **kwargs)

    def files(self) -> Iterable[Path]:
        skip_dirs = {".git", "__pycache__", "sandbox", "checkpoints", "node_modules"}
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = sorted(
                name for name in dirnames if name not in skip_dirs and not name.startswith(".tmp")
            )
            base = Path(dirpath)
            for name in sorted(filenames):
                path = base / name
                if path.is_symlink() or not path.is_file():
                    continue
                rel = path.relative_to(self.root).as_posix()
                if self._secret(rel, name):
                    continue
                yield path

    def tree_hash(self) -> str:
        import hashlib

        digest = hashlib.sha256()
        for path in self.files():
            rel = path.relative_to(self.root).as_posix()
            digest.update(rel.encode())
            digest.update(b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(65536), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        return digest.hexdigest()

    def _validate_paths(self, values: Sequence[str]) -> None:
        for value in values:
            if value.startswith("-") or value.startswith("--"):
                continue
            self.resolve(value)

    def validate_command(self, argv: Sequence[str]) -> None:
        if not argv or len(argv) > 64:
            raise CommandDenied("empty or oversized command")
        for arg in argv:
            if not isinstance(arg, str) or "\x00" in arg or "\n" in arg or len(arg) > 2000:
                raise CommandDenied("invalid argument")
        exe = Path(argv[0]).name
        if argv[0] != exe:
            raise CommandDenied("absolute or punctuated executable paths are denied")
        if exe == "python3":
            if len(argv) < 3 or argv[1] != "-m" or argv[2] not in {"unittest", "compileall", "py_compile"}:
                raise CommandDenied("only python3 -m unittest/compileall/py_compile is allowed")
            if argv[2] in {"compileall", "py_compile"}:
                self._validate_paths(argv[3:])
            return
        if exe == "git":
            self._validate_git(argv[1:])
            return
        if exe == "ls":
            self._validate_paths(argv[1:])
            return
        if exe == "wc":
            self._validate_paths(argv[1:])
            return
        if exe == "sha256sum":
            if "--check" in argv or "-c" in argv:
                raise CommandDenied("sha256sum --check is denied")
            self._validate_paths(argv[1:])
            return
        raise CommandDenied(f"executable not allowed: {exe}")

    def _validate_git(self, args: Sequence[str]) -> None:
        if not args:
            raise CommandDenied("git requires a subcommand")
        sub = args[0]
        if sub in {"push", "pull", "fetch", "clone", "remote", "submodule", "config", "reset", "clean"}:
            raise CommandDenied(f"git {sub} is denied")
        if sub == "status":
            allowed = {"--short", "--porcelain", "--branch", "-s", "-b", "--untracked-files=no"}
            if any(arg not in allowed for arg in args[1:]):
                raise CommandDenied("unsupported git status arguments")
            return
        if sub == "diff":
            banned = {"--no-index", "--ext-diff", "--textconv", "--output"}
            if any(arg in banned for arg in args[1:]):
                raise CommandDenied("external diff access is denied")
            paths = [arg for arg in args[1:] if not arg.startswith("-") and arg not in {"HEAD", "HEAD~1"}]
            self._validate_paths(paths)
            return
        if sub == "log":
            if any(arg.startswith("--output") or arg == "-p" for arg in args[1:]):
                raise CommandDenied("unsupported git log arguments")
            return
        if sub == "show":
            if any(arg.startswith("--output") for arg in args[1:]):
                raise CommandDenied("unsupported git show arguments")
            return
        if sub == "init":
            if any(arg not in {"-q", "--quiet"} for arg in args[1:]):
                raise CommandDenied("unsupported git init arguments")
            return
        if sub == "add":
            if any(arg in {"-A", "--all", "-u", "--update"} for arg in args[1:]):
                raise CommandDenied("git add requires explicit paths")
            paths = [arg for arg in args[1:] if not arg.startswith("-")]
            if not paths:
                raise CommandDenied("git add requires a path")
            self._validate_paths(paths)
            return
        if sub == "commit":
            if "--amend" in args[1:]:
                raise CommandDenied("amend is denied")
            if "-m" not in args[1:]:
                raise CommandDenied("git commit requires -m")
            return
        if sub == "rev-parse":
            allowed = {"HEAD", "--show-toplevel", "--is-inside-work-tree", "--verify"}
            if any(arg not in allowed and not arg.startswith("HEAD") for arg in args[1:]):
                raise CommandDenied("unsupported git rev-parse arguments")
            return
        if sub == "ls-files":
            self._validate_paths([arg for arg in args[1:] if not arg.startswith("-")])
            return
        raise CommandDenied(f"git subcommand not allowed: {sub}")

    def _environment(self, git_commit: bool) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/data/data/com.termux/files/usr/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "HOME": str(self._sandbox_home),
            "XDG_CONFIG_HOME": str(self._sandbox_home / ".config"),
            "XDG_CACHE_HOME": str(self._sandbox_home / ".cache"),
            "TMPDIR": str(self._sandbox_tmp),
            "PYTHONPATH": str(self.root),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "",
            "PIP_NO_INDEX": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_ASKPASS": "/bin/false",
            "SSH_ASKPASS": "/bin/false",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        if git_commit:
            env.update(
                {
                    "GIT_AUTHOR_NAME": "SOO Runner",
                    "GIT_AUTHOR_EMAIL": "soo@localhost",
                    "GIT_COMMITTER_NAME": "SOO Runner",
                    "GIT_COMMITTER_EMAIL": "soo@localhost",
                }
            )
        return env

    def _limits(self) -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (int(self.limits["subprocess_cpu_seconds"]),) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (int(self.limits["subprocess_file_size_bytes"]),) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_AS, (3072 * 1024 * 1024, 3072 * 1024 * 1024))

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> dict:
        argv = list(argv)
        self.validate_command(argv)
        workdir = self.resolve(cwd) if cwd is not None else self.root
        if not workdir.is_dir():
            raise SecurityError(f"working directory is not a directory: {workdir}")
        limit = float(timeout if timeout is not None else self.limits["subprocess_timeout_seconds"])
        env = self._environment(git_commit=(len(argv) > 1 and argv[0] == "git" and argv[1] == "commit"))
        started = time.monotonic()
        proc = subprocess.Popen(
            argv,
            cwd=str(workdir),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=self._limits,
            close_fds=True,
        )
        timed_out = False
        try:
            out, err = proc.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        cap = int(self.limits["max_output_bytes"])
        stdout = out[:cap].decode("utf-8", "replace")
        stderr = err[:cap].decode("utf-8", "replace")
        if len(out) > cap:
            stdout += "\n[truncated stdout]"
        if len(err) > cap:
            stderr += "\n[truncated stderr]"
        return {
            "ok": proc.returncode == 0 and not timed_out,
            "returncode": proc.returncode,
            "timed_out": timed_out,
            "duration_ms": elapsed_ms,
            "argv": argv,
            "cwd": str(workdir),
            "stdout": stdout,
            "stderr": stderr,
        }


def which(name: str) -> str | None:
    return shutil.which(name)
