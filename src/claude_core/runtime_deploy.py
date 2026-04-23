from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


MANIFEST_NAME = 'claude_core_deploy_manifest.json'


class DeployVerificationError(RuntimeError):
    pass


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _iter_source_files(package_src: Path):
    for path in sorted(package_src.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            yield path


def deploy_shared_core(
    shared_root: Path,
    runtime_root: Path | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    shared_root = shared_root.resolve()
    runtime_root = (runtime_root or (Path.home() / '.claude' / 'scripts')).resolve()
    package_src = shared_root / 'src' / 'claude_core'
    target = runtime_root / 'claude_core'
    manifest = runtime_root / MANIFEST_NAME

    source_files = []
    changed: list[str] = []
    for src in _iter_source_files(package_src):
        rel = src.relative_to(package_src).as_posix()
        digest = _sha256_of(src)
        source_files.append({'path': rel, 'sha256': digest})

    plan = {
        'shared_root': str(shared_root),
        'runtime_root': str(runtime_root),
        'package_src': str(package_src),
        'target': str(target),
        'manifest': str(manifest),
        'deployed_at': datetime.now(timezone.utc).isoformat(),
        'dry_run': dry_run,
        'files': source_files,
        'changed': changed,
    }
    if dry_run:
        return plan

    runtime_root.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)

    expected_rels = {entry['path'] for entry in source_files}

    # remove stale files in target that are no longer present in source
    if target.exists():
        for existing in sorted(target.rglob('*')):
            if not existing.is_file() or '__pycache__' in existing.parts:
                continue
            rel = existing.relative_to(target).as_posix()
            if rel not in expected_rels:
                existing.unlink()
                changed.append(f'deleted:{rel}')

    for entry in source_files:
        rel = entry['path']
        src = package_src / rel
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and _sha256_of(dst) == entry['sha256']:
            continue
        shutil.copy2(src, dst)
        changed.append(f'updated:{rel}')

    manifest.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    return plan


def verify_deployment(runtime_root: Path | None = None) -> dict:
    runtime_root = (runtime_root or (Path.home() / '.claude' / 'scripts')).resolve()
    manifest_path = runtime_root / MANIFEST_NAME
    target = runtime_root / 'claude_core'

    if not manifest_path.exists():
        raise DeployVerificationError(f'manifest missing: {manifest_path}')
    if not target.exists():
        raise DeployVerificationError(f'deploy target missing: {target}')

    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = {entry['path']: entry['sha256'] for entry in manifest.get('files', [])}

    missing: list[str] = []
    drifted: list[str] = []
    for rel, sha in expected.items():
        dst = target / rel
        if not dst.exists():
            missing.append(rel)
            continue
        if _sha256_of(dst) != sha:
            drifted.append(rel)

    if missing or drifted:
        raise DeployVerificationError(
            f'deployment drift detected: missing={missing} drifted={drifted}'
        )

    return {'runtime_root': str(runtime_root), 'verified_files': len(expected)}
