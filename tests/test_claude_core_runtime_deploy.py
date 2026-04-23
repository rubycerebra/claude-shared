from pathlib import Path

import pytest

from claude_core.runtime_deploy import (
    DeployVerificationError,
    deploy_shared_core,
    verify_deployment,
)


def _make_fake_shared(tmp_path: Path) -> Path:
    shared = tmp_path / 'claude-shared'
    package = shared / 'src' / 'claude_core'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('__version__ = "0"\n', encoding='utf-8')
    (package / 'hooks.py').write_text('def noop():\n    return 1\n', encoding='utf-8')
    return shared


def test_deploy_shared_core_dry_run_reports_targets(tmp_path: Path):
    shared = _make_fake_shared(tmp_path)
    runtime = tmp_path / '.claude' / 'scripts'
    plan = deploy_shared_core(shared, runtime_root=runtime, dry_run=True)
    assert plan['package_src'].endswith('src/claude_core')
    assert plan['target'].endswith('.claude/scripts/claude_core')
    assert plan['dry_run'] is True


def test_deploy_shared_core_writes_files_and_manifest(tmp_path: Path):
    shared = _make_fake_shared(tmp_path)
    runtime = tmp_path / '.claude' / 'scripts'
    plan = deploy_shared_core(shared, runtime_root=runtime)
    target = Path(plan['target'])
    manifest = Path(plan['manifest'])
    assert (target / '__init__.py').is_file()
    assert (target / 'hooks.py').is_file()
    assert manifest.is_file()
    assert plan['files'], 'manifest plan must record per-file checksums'
    assert all('sha256' in entry for entry in plan['files'])


def test_deploy_is_idempotent_without_source_changes(tmp_path: Path):
    shared = _make_fake_shared(tmp_path)
    runtime = tmp_path / '.claude' / 'scripts'
    first = deploy_shared_core(shared, runtime_root=runtime)
    target = Path(first['target']) / '__init__.py'
    mtime_before = target.stat().st_mtime_ns
    second = deploy_shared_core(shared, runtime_root=runtime)
    mtime_after = target.stat().st_mtime_ns
    assert mtime_before == mtime_after, 'unchanged files should not be rewritten'
    assert second['changed'] == [], 'idempotent re-run should report no changes'


def test_verify_deployment_passes_fresh_deploy(tmp_path: Path):
    shared = _make_fake_shared(tmp_path)
    runtime = tmp_path / '.claude' / 'scripts'
    deploy_shared_core(shared, runtime_root=runtime)
    verify_deployment(runtime_root=runtime)  # should not raise


def test_verify_deployment_detects_drift(tmp_path: Path):
    shared = _make_fake_shared(tmp_path)
    runtime = tmp_path / '.claude' / 'scripts'
    plan = deploy_shared_core(shared, runtime_root=runtime)
    (Path(plan['target']) / 'hooks.py').write_text('tampered\n', encoding='utf-8')
    with pytest.raises(DeployVerificationError):
        verify_deployment(runtime_root=runtime)
