from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import shutil


def deploy_shared_core(shared_root: Path, runtime_root: Path | None = None, *, dry_run: bool = False) -> dict:
    shared_root = shared_root.resolve()
    runtime_root = (runtime_root or (Path.home() / '.claude' / 'scripts')).resolve()
    package_src = shared_root / 'src' / 'claude_core'
    target = runtime_root / 'claude_core'
    manifest = runtime_root / 'claude_core_deploy_manifest.json'

    plan = {
        'shared_root': str(shared_root),
        'runtime_root': str(runtime_root),
        'package_src': str(package_src),
        'target': str(target),
        'manifest': str(manifest),
        'deployed_at': datetime.now(timezone.utc).isoformat(),
        'dry_run': dry_run,
    }
    if dry_run:
        return plan

    runtime_root.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(package_src, target)
    manifest.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    return plan
