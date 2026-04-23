from __future__ import annotations

import os
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
