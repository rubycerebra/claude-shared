from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .device_roles import DeviceRole, guess_device_role


class LockHeldError(RuntimeError):
    pass


def pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def current_device_role() -> DeviceRole:
    return guess_device_role()


@dataclass
class CooldownGate:
    state_file: Path
    cooldown_seconds: int

    def _read_last(self) -> int | None:
        try:
            raw = self.state_file.read_text(encoding="utf-8").strip()
            return int(raw)
        except (FileNotFoundError, ValueError):
            return None

    def should_run(self, now: float | None = None) -> bool:
        last = self._read_last()
        if last is None:
            return True
        current = int(now if now is not None else time.time())
        return (current - last) >= self.cooldown_seconds

    def mark_ran(self, now: float | None = None) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        stamp = int(now if now is not None else time.time())
        self.state_file.write_text(str(stamp), encoding="utf-8")


class LockFile(AbstractContextManager):
    def __init__(self, path: Path):
        self.path = path
        self.held = False

    def __enter__(self) -> "LockFile":
        if self.path.exists():
            raw = self.path.read_text(encoding="utf-8").strip()
            try:
                existing_pid = int(raw)
            except ValueError:
                existing_pid = None
            if existing_pid is not None and pid_is_alive(existing_pid):
                raise LockHeldError(f"lock held by pid {existing_pid}: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(os.getpid()), encoding="utf-8")
        self.held = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.held:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.held = False


def _default_ppid_lookup(pid: int) -> int | None:
    try:
        res = subprocess.run(
            ["ps", "-p", str(pid), "-o", "ppid="],
            capture_output=True, text=True, timeout=2,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if res.returncode != 0:
        return None
    out = res.stdout.strip()
    if not out:
        return None
    try:
        return int(out.split()[0])
    except (ValueError, IndexError):
        return None


def walk_ancestor_pids(
    pid: int,
    *,
    ppid_lookup: Callable[[int], int | None] | None = None,
    max_depth: int = 64,
) -> set[int]:
    lookup = ppid_lookup or _default_ppid_lookup
    seen: set[int] = {pid}
    current = pid
    for _ in range(max_depth):
        ppid = lookup(current)
        if ppid is None or ppid <= 0 or ppid in seen:
            break
        seen.add(ppid)
        current = ppid
    return seen


def dispatch_by_role(
    *,
    mac: Callable[[], object] | None = None,
    nuc: Callable[[], object] | None = None,
    fallback: Callable[[], object] | None = None,
) -> object:
    role = current_device_role()
    if role == DeviceRole.MAC_INTERFACE and mac is not None:
        return mac()
    if role == DeviceRole.NUC_RUNTIME and nuc is not None:
        return nuc()
    if fallback is not None:
        return fallback()
    return None


# --- session-end helpers ---

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def check_gate(env_name: str, flag_file: Path | str | None = None) -> bool:
    """Return True if a gate is enabled via env var or flag file."""
    env_val = os.environ.get(env_name, "").strip().lower()
    if env_val in _TRUTHY:
        return True
    if flag_file is not None:
        path = Path(flag_file)
        if path.is_file():
            try:
                file_val = path.read_text(encoding="utf-8").strip().lower()
            except OSError:
                file_val = ""
            if file_val in _TRUTHY:
                return True
    return False


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
    )


def session_end_commit_push(
    projects: list[Path],
    *,
    allow_commit: bool = True,
    allow_push: bool = True,
    reset_patterns: tuple[str, ...] = (".cache/", ".helpers/__pycache__/"),
    co_author: str = "Claude Sonnet 4.5 <noreply@anthropic.com>",
) -> list[dict]:
    """Run commit + push across project dirs. Returns per-project results."""
    from datetime import datetime

    results = []
    for project in projects:
        project = Path(project)
        info: dict = {"project": str(project), "committed": False, "pushed": False}

        if not project.is_dir():
            info["skipped"] = "not a directory"
            results.append(info)
            continue

        if not (project / ".git").exists() and _git("rev-parse", "--git-dir", cwd=project).returncode != 0:
            info["skipped"] = "not a git repo"
            results.append(info)
            continue

        if allow_commit:
            porcelain = _git("status", "--porcelain", cwd=project)
            if porcelain.stdout.strip():
                _git("add", "-A", cwd=project)
                for pattern in reset_patterns:
                    _git("reset", "--", pattern, cwd=project)

                msg = (
                    f"Session auto-commit: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"Co-Authored-By: {co_author}"
                )
                commit_result = _git("commit", "-m", msg, cwd=project)
                info["committed"] = commit_result.returncode == 0

        if allow_push:
            branch_result = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=project)
            branch = branch_result.stdout.strip()
            if branch:
                ls_remote = _git("ls-remote", "--exit-code", "--heads", "origin", branch, cwd=project)
                if ls_remote.returncode == 0:
                    push = _git("push", cwd=project)
                else:
                    push = _git("push", "-u", "origin", branch, cwd=project)
                info["pushed"] = push.returncode == 0

        results.append(info)
    return results


_ROLE_KEYWORDS = {
    "mac": DeviceRole.MAC_INTERFACE,
    "nuc": DeviceRole.NUC_RUNTIME,
    "unknown": DeviceRole.UNKNOWN,
}

SEQUENCED_LAST_FILENAME = "sequenced-autopilot.last"
SEQUENCED_LOCK_FILENAME = "sequenced-autopilot.lock"


def sequenced_gate_status(
    state_dir: Path,
    *,
    cooldown_seconds: int,
    now: float | None = None,
) -> dict:
    state_dir = Path(state_dir)
    last_file = state_dir / SEQUENCED_LAST_FILENAME
    lock_file = state_dir / SEQUENCED_LOCK_FILENAME

    current = int(now if now is not None else time.time())
    gate = CooldownGate(last_file, cooldown_seconds=cooldown_seconds)
    if not gate.should_run(now=current):
        last = int(last_file.read_text(encoding="utf-8").strip()) if last_file.exists() else None
        return {
            "should_run": False,
            "blocked_by": "cooldown",
            "elapsed": current - last if last is not None else None,
            "cooldown_seconds": cooldown_seconds,
        }

    if lock_file.exists():
        raw = lock_file.read_text(encoding="utf-8").strip()
        try:
            lock_pid = int(raw)
        except ValueError:
            lock_pid = None
        if lock_pid is not None and pid_is_alive(lock_pid):
            return {
                "should_run": False,
                "blocked_by": "lock",
                "lock_pid": lock_pid,
                "lock_file": str(lock_file),
            }

    return {"should_run": True, "blocked_by": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude_core.hooks")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check-role", help="Exit 0 iff current device role matches keyword")
    check.add_argument("role", help="One of: mac, nuc, unknown")

    gate = sub.add_parser(
        "sequenced-gate",
        help="Exit 0 iff cooldown has expired and no live lock holds the autopilot",
    )
    gate.add_argument("--state-dir", required=True)
    gate.add_argument("--cooldown-seconds", type=int, required=True)

    end = sub.add_parser(
        "session-end",
        help="Commit and push across project dirs with optional gating",
    )
    end.add_argument("projects", nargs="+", help="Project directories to process")
    end.add_argument("--check-gates", action="store_true", help="Check commit/push gate files before acting")
    end.add_argument(
        "--config-dir",
        default=str(Path.home() / ".claude" / "config"),
        help="Directory containing gate flag files",
    )

    args = parser.parse_args(argv)

    if args.cmd == "check-role":
        expected = _ROLE_KEYWORDS.get(args.role.lower())
        if expected is None:
            print(
                f"error: unknown role keyword {args.role!r} (expected mac/nuc/unknown)",
                file=sys.stderr,
            )
            return 2
        return 0 if current_device_role() == expected else 1

    if args.cmd == "sequenced-gate":
        status = sequenced_gate_status(
            Path(args.state_dir),
            cooldown_seconds=args.cooldown_seconds,
        )
        if status["should_run"]:
            return 0
        reason = status.get("blocked_by", "unknown")
        if reason == "cooldown":
            print(
                f"[SEQUENCED] cooldown active ({status.get('elapsed')}s < {status.get('cooldown_seconds')}s)",
                file=sys.stderr,
            )
        elif reason == "lock":
            print(
                f"[SEQUENCED] already running (pid {status.get('lock_pid')})",
                file=sys.stderr,
            )
        else:
            print(f"[SEQUENCED] blocked: {reason}", file=sys.stderr)
        return 1

    if args.cmd == "session-end":
        allow_commit = True
        allow_push = True
        if args.check_gates:
            config_dir = Path(args.config_dir)
            allow_commit = check_gate(
                "CLAUDE_SESSION_END_ALLOW_COMMIT",
                config_dir / "session-end-allow-commit",
            )
            allow_push = check_gate(
                "CLAUDE_SESSION_END_ALLOW_PUSH",
                config_dir / "session-end-allow-push",
            )
        project_paths = [Path(p) for p in args.projects]
        results = session_end_commit_push(
            project_paths,
            allow_commit=allow_commit,
            allow_push=allow_push,
        )
        import json
        print(json.dumps(results, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
