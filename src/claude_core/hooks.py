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

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
