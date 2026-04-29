from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import os
import platform


class DeviceRole(str, Enum):
    NUC_RUNTIME = "nuc_runtime"
    MAC_INTERFACE = "mac_interface"
    UNKNOWN = "unknown"


class SyncSurfacePolicy(str, Enum):
    SINGLE_WRITER = "single_writer"
    REPLICATED_READONLY = "replicated_readonly"
    LOCAL_OVERLAY = "local_overlay"
    DEVICE_LOCAL = "device_local"


@dataclass(frozen=True)
class DeployTarget:
    name: str
    root: Path
    role: DeviceRole
    writable: bool
    notes: str = ""


@dataclass(frozen=True)
class SurfaceDefinition:
    name: str
    path: Path
    owner: str
    classification: str
    sync_policy: SyncSurfacePolicy
    deploy_target: str | None = None
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


def guess_device_role() -> DeviceRole:
    override = os.environ.get("CLAUDE_DEVICE_ROLE", "").strip().lower()
    if override in {role.value for role in DeviceRole}:
        return DeviceRole(override)

    system = platform.system()
    if system == "Darwin":
        return DeviceRole.MAC_INTERFACE
    if system == "Windows":
        return DeviceRole.NUC_RUNTIME

    hostname = platform.node().lower()
    if "nuc" in hostname:
        return DeviceRole.NUC_RUNTIME
    if "mac" in hostname or "book" in hostname:
        return DeviceRole.MAC_INTERFACE
    return DeviceRole.UNKNOWN
