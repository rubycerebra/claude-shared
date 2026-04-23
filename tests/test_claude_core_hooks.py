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


# --- walk_ancestor_pids ---

def test_walk_ancestor_pids_follows_chain_to_init():
    chain = {100: 90, 90: 80, 80: 1, 1: 0}
    ancestors = hooks_mod.walk_ancestor_pids(100, ppid_lookup=lambda pid: chain.get(pid, 0))
    assert ancestors == {100, 90, 80, 1}


def test_walk_ancestor_pids_stops_on_cycle():
    # Hypothetical broken ps output: self-parent loop
    chain = {50: 40, 40: 50}
    ancestors = hooks_mod.walk_ancestor_pids(50, ppid_lookup=lambda pid: chain.get(pid, 0))
    assert ancestors == {50, 40}


def test_walk_ancestor_pids_stops_when_ppid_missing():
    # Lookup returns None when pid is no longer visible
    ancestors = hooks_mod.walk_ancestor_pids(7, ppid_lookup=lambda pid: None)
    assert ancestors == {7}


def test_walk_ancestor_pids_ignores_invalid_ppid_values():
    # ps can return 0, negatives, or huge numbers when a pid is gone
    chain = {9: -1}
    ancestors = hooks_mod.walk_ancestor_pids(9, ppid_lookup=lambda pid: chain.get(pid))
    assert ancestors == {9}


# --- cli: check-role ---

def test_cli_check_role_returns_zero_when_matching(monkeypatch, capsys):
    monkeypatch.setattr(hooks_mod, "current_device_role", lambda: DeviceRole.MAC_INTERFACE)
    rc = hooks_mod.main(["check-role", "mac"])
    assert rc == 0


def test_cli_check_role_returns_nonzero_when_not_matching(monkeypatch):
    monkeypatch.setattr(hooks_mod, "current_device_role", lambda: DeviceRole.NUC_RUNTIME)
    rc = hooks_mod.main(["check-role", "mac"])
    assert rc == 1


def test_cli_check_role_accepts_nuc_keyword(monkeypatch):
    monkeypatch.setattr(hooks_mod, "current_device_role", lambda: DeviceRole.NUC_RUNTIME)
    rc = hooks_mod.main(["check-role", "nuc"])
    assert rc == 0


def test_cli_check_role_rejects_unknown_keyword():
    rc = hooks_mod.main(["check-role", "moon"])
    assert rc == 2
