from pathlib import Path

from claude_core.session_context import save_conversation


def test_save_conversation_writes_to_project_inbox(tmp_path: Path):
    (tmp_path / 'CLAUDE.md').write_text('# test\n', encoding='utf-8')
    path = save_conversation('hello world', project_root=tmp_path)
    assert path.parent == tmp_path / 'inbox'
    assert 'hello world' in path.read_text(encoding='utf-8')
