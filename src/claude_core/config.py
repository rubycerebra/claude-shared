from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from .device_roles import DeviceRole, guess_device_role


@dataclass(frozen=True)
class SharedPaths:
    project_root: Path
    claude_shared_root: Path
    runtime_root: Path
    cache_root: Path


@dataclass(frozen=True)
class ProjectRuntimeConfig:
    project_name: str
    project_root: Path
    device_role: DeviceRole
    paths: SharedPaths


def discover_project_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    if start.is_file():
        start = start.parent
    for candidate in [start, *start.parents]:
        if (candidate / 'CLAUDE.md').exists() or (candidate / '.helpers').exists():
            return candidate
    return start


def _candidate_shared_roots(project_root: Path):
    seen: set[Path] = set()
    env = os.environ.get('CLAUDE_SHARED_ROOT')
    if env:
        candidate = Path(env).expanduser().resolve()
        if candidate not in seen:
            seen.add(candidate)
            yield candidate

    for parent in [project_root.parent, *project_root.parents]:
        direct = (parent / 'claude-shared').resolve()
        nested = (parent / 'claude-shared' / project_root.name).resolve()
        for candidate in (direct, nested):
            if candidate not in seen:
                seen.add(candidate)
                yield candidate

    fallback = (Path.home() / 'Documents' / 'Claude Projects' / 'claude-shared').resolve()
    if fallback not in seen:
        yield fallback


def discover_claude_shared_root(project_root: Path | None = None) -> Path:
    project_root = discover_project_root(project_root)
    fallback = (Path.home() / 'Documents' / 'Claude Projects' / 'claude-shared').resolve()
    existing_candidate: Path | None = None
    for candidate in _candidate_shared_roots(project_root):
        if (candidate / 'src' / 'claude_core' / '__init__.py').exists() or (candidate / 'pyproject.toml').exists():
            return candidate
        if existing_candidate is None and candidate.exists():
            existing_candidate = candidate
    return existing_candidate or fallback


def build_runtime_config(project_root: Path | None = None) -> ProjectRuntimeConfig:
    project_root = discover_project_root(project_root)
    claude_shared_root = discover_claude_shared_root(project_root)
    runtime_root = Path.home() / '.claude'
    cache_root = runtime_root / 'cache'
    paths = SharedPaths(
        project_root=project_root,
        claude_shared_root=claude_shared_root,
        runtime_root=runtime_root,
        cache_root=cache_root,
    )
    return ProjectRuntimeConfig(
        project_name=project_root.name,
        project_root=project_root,
        device_role=guess_device_role(),
        paths=paths,
    )
