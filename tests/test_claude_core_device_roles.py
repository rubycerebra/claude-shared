from pathlib import Path

from claude_core.config import build_runtime_config
from claude_core.device_roles import DeviceRole, guess_device_role


def test_runtime_config_finds_claude_shared_from_sibling_repo(tmp_path: Path):
    projects = tmp_path / 'Claude Projects'
    health = projects / 'HEALTH'
    shared = projects / 'claude-shared'
    (health / '.helpers').mkdir(parents=True)
    (health / 'CLAUDE.md').write_text('# test\n', encoding='utf-8')
    shared.mkdir(parents=True)

    cfg = build_runtime_config(health)
    assert cfg.project_root == health
    assert cfg.paths.claude_shared_root == shared


def test_guess_device_role_is_known_enum_value():
    assert guess_device_role() in {DeviceRole.MAC_INTERFACE, DeviceRole.NUC_RUNTIME, DeviceRole.UNKNOWN}
