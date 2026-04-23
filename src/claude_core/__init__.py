from .config import ProjectRuntimeConfig, SharedPaths
from .device_roles import DeployTarget, DeviceRole, SurfaceDefinition, SyncSurfacePolicy, guess_device_role

__all__ = [
    "DeployTarget",
    "DeviceRole",
    "ProjectRuntimeConfig",
    "SharedPaths",
    "SurfaceDefinition",
    "SyncSurfacePolicy",
    "guess_device_role",
]

__version__ = "0.1.0"
