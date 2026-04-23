from __future__ import annotations

import os
from pathlib import Path

import pytest

from claude_core import hooks as hooks_mod
from claude_core.device_roles import DeviceRole


# --- CooldownGate ---

def test_cooldown_gate_first_run_is_allowed(tmp_path: Path):
    gate = hooks_mod.CooldownGate(tmp_path / "last", cooldown_seconds=60)
    assert gate.should_run(now=1_000) is True


def test_cooldown_gate_within_window_is_blocked(tmp_path: Path):
    state = tmp_path / "last"
    gate = hooks_mod.CooldownGate(state, cooldown_seconds=60)
    gate.mark_ran(now=1_000)
    assert gate.should_run(now=1_030) is False


def test_cooldown_gate_after_window_is_allowed(tmp_path: Path):
    state = tmp_path / "last"
    gate = hooks_mod.CooldownGate(state, cooldown_seconds=60)
    gate.mark_ran(now=1_000)
    assert gate.should_run(now=1_061) is True


def test_cooldown_gate_ignores_malformed_state(tmp_path: Path):
    state = tmp_path / "last"
    state.write_text("not-a-number\n", encoding="utf-8")
    gate = hooks_mod.CooldownGate(state, cooldown_seconds=60)
    assert gate.should_run(now=1_000) is True


# --- LockFile ---

def test_lockfile_writes_pid_while_held(tmp_path: Path):
    path = tmp_path / "autopilot.lock"
    with hooks_mod.LockFile(path) as lock:
        assert lock.held is True
        assert path.read_text(encoding="utf-8").strip() == str(os.getpid())
    assert not path.exists()


def test_lockfile_blocks_when_live_pid_holds_it(tmp_path: Path):
    path = tmp_path / "autopilot.lock"
    path.write_text(str(os.getpid()), encoding="utf-8")

    with pytest.raises(hooks_mod.LockHeldError):
        with hooks_mod.LockFile(path):
            pass


def test_lockfile_steals_stale_lock_when_pid_dead(tmp_path: Path, monkeypatch):
    path = tmp_path / "autopilot.lock"
    path.write_text("999999", encoding="utf-8")

    def _pid_is_dead(pid: int) -> bool:
        return False

    monkeypatch.setattr(hooks_mod, "pid_is_alive", _pid_is_dead)

    with hooks_mod.LockFile(path) as lock:
        assert lock.held is True


# --- device dispatch ---

def test_dispatch_by_role_runs_mac_callable_on_darwin(monkeypatch):
    monkeypatch.setattr(hooks_mod, "current_device_role", lambda: DeviceRole.MAC_INTERFACE)
    calls: list[str] = []
    hooks_mod.dispatch_by_role(
        mac=lambda: calls.append("mac"),
        nuc=lambda: calls.append("nuc"),
    )
    assert calls == ["mac"]


def test_dispatch_by_role_runs_nuc_callable_on_windows(monkeypatch):
    monkeypatch.setattr(hooks_mod, "current_device_role", lambda: DeviceRole.NUC_RUNTIME)
    calls: list[str] = []
    hooks_mod.dispatch_by_role(
        mac=lambda: calls.append("mac"),
        nuc=lambda: calls.append("nuc"),
    )
    assert calls == ["nuc"]


def test_dispatch_by_role_falls_back_when_role_unknown(monkeypatch):
    monkeypatch.setattr(hooks_mod, "current_device_role", lambda: DeviceRole.UNKNOWN)
    calls: list[str] = []
    hooks_mod.dispatch_by_role(
        mac=lambda: calls.append("mac"),
        nuc=lambda: calls.append("nuc"),
        fallback=lambda: calls.append("fallback"),
    )
    assert calls == ["fallback"]
