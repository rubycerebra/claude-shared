from pathlib import Path

from claude_core.runtime_deploy import deploy_shared_core


def test_deploy_shared_core_dry_run_reports_targets(tmp_path: Path):
    shared = tmp_path / 'claude-shared'
    package = shared / 'src' / 'claude_core'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('__version__ = "0"\n', encoding='utf-8')
    runtime = tmp_path / '.claude' / 'scripts'
    plan = deploy_shared_core(shared, runtime_root=runtime, dry_run=True)
    assert plan['package_src'].endswith('src/claude_core')
    assert plan['target'].endswith('.claude/scripts/claude_core')
