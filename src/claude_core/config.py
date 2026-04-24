from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from .device_roles import DeviceRole, guess_device_role


@dataclass(frozen=True)
class SharedPaths:
    project_root: Path
    claude_shared_root: Path
    runtime_root: Path        # ~/.claude
    cache_root: Path           # ~/.claude/cache

    # --- Cache files ---

    @property
    def session_data(self) -> Path:
        return self.cache_root / "session-data.json"

    @property
    def health_live(self) -> Path:
        return self.cache_root / "health-live.json"

    @property
    def diarium_images_dir(self) -> Path:
        return self.cache_root / "diarium-images"

    @property
    def diarium_md_dir(self) -> Path:
        return self.cache_root / "diarium-md"

    @property
    def akiflow_tracker_dir(self) -> Path:
        return self.cache_root / "akiflow-tracker"

    # --- Config files ---

    @property
    def config_dir(self) -> Path:
        return self.runtime_root / "config"

    @property
    def daemon_config(self) -> Path:
        return self.runtime_root / "daemon" / "config.json"

    @property
    def transcription_fixes(self) -> Path:
        return self.config_dir / "transcription-fixes.json"

    @property
    def secrets(self) -> Path:
        return self.runtime_root / "secrets.json"

    # --- Scripts ---

    @property
    def scripts_dir(self) -> Path:
        return self.runtime_root / "scripts"

    @property
    def shared_lib_dir(self) -> Path:
        return self.scripts_dir / "shared"

    # --- External data roots ---

    @property
    def gdrive_roots(self) -> list[Path]:
        """Google Drive root candidates (Mac stream, Mac mirror, Windows drive letters)."""
        return [
            Path.home() / "My Drive (james.cherry01@gmail.com)",
            Path.home() / "Library" / "CloudStorage" / "GoogleDrive-james.cherry01@gmail.com" / "My Drive",
            *(Path(f"{d}:/My Drive") for d in "GHIJKLMNOPQRSTUVWXYZ"),
            *(Path(f"/mnt/{d.lower()}") / "My Drive" for d in "GHIJKLMNOPQRSTUVWXYZ"),
        ]

    @property
    def diarium_export_roots(self) -> list[Path]:
        """Candidate Diarium export directories across devices."""
        return [
            Path("C:/SyncData/Diarium-Export"),
            *(root / "Diarium" / "Export" for root in self.gdrive_roots),
        ]

    @property
    def apple_health_roots(self) -> list[Path]:
        """Candidate Apple Health export directories across devices."""
        return [root / "Apple Health" for root in self.gdrive_roots]

    @property
    def alter_transcripts_dir(self) -> Path:
        return Path.home() / "Library" / "Application Support" / "Alter" / "Transcripts"

    # --- Session-end gate files ---

    @property
    def commit_gate_file(self) -> Path:
        return self.config_dir / "session-end-allow-commit"

    @property
    def push_gate_file(self) -> Path:
        return self.config_dir / "session-end-allow-push"

    # --- Daemon config candidates (multi-device) ---

    @property
    def daemon_config_candidates(self) -> list[Path]:
        """Daemon config paths tried in order (NUC service-local, user profile, Windows fallback)."""
        return [
            Path("C:/SyncData/claude-daemon/config.json"),
            self.daemon_config,
            Path("C:/Users/James Cherry/.claude/daemon/config.json"),
        ]


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
